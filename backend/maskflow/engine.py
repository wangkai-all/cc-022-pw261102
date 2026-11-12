from __future__ import annotations

import datetime as dt
import decimal
from pathlib import Path
from typing import Any

import duckdb

from .mapping import AllocationError, date_offset, allocate_namespace
from .rules import (
    MASK_STRATEGIES,
    NamespaceSpec,
    RuleReport,
    Ruleset,
    collect_namespaces,
    validate_rules,
)
from .schema import COLUMN_TYPES, STRATEGY_LABELS, TABLE_ORDER


class MaskingError(RuntimeError):
    pass


class SourceDataError(MaskingError):
    pass


class RuleValidationError(MaskingError):
    def __init__(self, report: RuleReport):
        self.report = report
        super().__init__("；".join(report.errors) if report.errors else "规则校验失败")


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _normalise_sql(expression: str, kind: str) -> str:
    if kind == "fake_phone":
        return f"regexp_replace(CAST({expression} AS VARCHAR), '[^0-9]', '', 'g')"
    if kind == "fake_email":
        return f"lower(trim(CAST({expression} AS VARCHAR)))"
    return f"trim(CAST({expression} AS VARCHAR))"


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    return value


def _table_path(source_dir: Path, table: str) -> Path:
    return source_dir / f"{table}.csv"


def read_source_schema(source_dir: Path) -> dict[str, list[str]]:
    con = duckdb.connect()
    schema: dict[str, list[str]] = {}
    try:
        for table in TABLE_ORDER:
            path = _table_path(source_dir, table)
            if not path.exists():
                raise SourceDataError(f"缺少源数据文件 {path.name}")
            description = con.execute(
                f"DESCRIBE SELECT * FROM read_csv_auto({_sql_literal(str(path))}, "
                "header=true, all_varchar=true)"
            ).fetchall()
            schema[table] = [row[0] for row in description]
    finally:
        con.close()
    return schema


def _load_source(con: duckdb.DuckDBPyConnection, source_dir: Path) -> dict[str, list[str]]:
    schema: dict[str, list[str]] = {}
    for table in TABLE_ORDER:
        path = _table_path(source_dir, table)
        if not path.exists():
            raise SourceDataError(f"缺少源数据文件 {path.name}")
        expected = COLUMN_TYPES[table]
        description = con.execute(
            f"DESCRIBE SELECT * FROM read_csv_auto({_sql_literal(str(path))}, "
            "header=true, all_varchar=true)"
        ).fetchall()
        actual = [row[0] for row in description]
        if actual != list(expected):
            raise SourceDataError(
                f"{path.name} 的列与内置数据集结构不一致：期望 {list(expected)}，实际 {actual}"
            )
        select_list = ", ".join(
            f"CAST({_quote_identifier(column)} AS {dtype}) AS {_quote_identifier(column)}"
            for column, dtype in expected.items()
        )
        con.execute(
            f"CREATE OR REPLACE TABLE {_quote_identifier('src_' + table)} AS "
            f"SELECT {select_list} FROM read_csv_auto({_sql_literal(str(path))}, "
            "header=true, all_varchar=true)"
        )
        schema[table] = list(expected)
    return schema


class MaskingEngine:
    def __init__(self, source_dir: Path, seed: str, rules: Ruleset, seed_source: str = "local"):
        self.source_dir = Path(source_dir)
        self.seed = seed
        self.seed_source = seed_source
        self.rules = rules
        self.con = duckdb.connect()
        self.schema: dict[str, list[str]] = {}
        self.namespace_specs: dict[str, NamespaceSpec] = {}
        self.mapping_stats: list[dict] = []
        self.banned_values: dict[str, set[str]] = {}
        self.offset_stats: dict[str, Any] = {}
        self.report: RuleReport | None = None
        self.prepared = False

    @property
    def rule_version(self) -> str:
        return self.rules.version

    @property
    def rules_hash(self) -> str:
        return self.report.rules_hash if self.report else ""

    def prepare(self) -> "MaskingEngine":
        if self.prepared:
            return self
        self.schema = _load_source(self.con, self.source_dir)
        report = validate_rules(self.rules, self.schema)
        self.report = report
        if not report.valid:
            raise RuleValidationError(report)
        self.namespace_specs, namespace_errors = collect_namespaces(self.rules)
        if namespace_errors:
            raise MaskingError("；".join(namespace_errors))
        self._build_mappings()
        self._build_offsets()
        self._transform()
        self.prepared = True
        return self

    # ------------------------------------------------------------------ mappings
    def _tenant_expr(self, alias: str = "t") -> str:
        column = _quote_identifier(self.rules.tenant_column)
        return f"CAST(COALESCE({alias}.{column}, '') AS VARCHAR)"

    def _identity_expr(self, column: str, alias: str = "t") -> str:
        return f"COALESCE(CAST({alias}.{_quote_identifier(column)} AS VARCHAR), '')"

    def _mask_join(
        self, table: str, column: str, rule, index: int
    ) -> tuple[str, str]:
        """Return (left join clause, select expression) for one masked column."""
        alias = f"mm_{index}"
        if rule.strategy == "surrogate_id":
            namespace = _sql_literal(rule.namespace)
            norm = _normalise_sql(f"t.{_quote_identifier(column)}", "surrogate_id")
            join = (
                f"LEFT JOIN mask_map {alias} ON {alias}.namespace = {namespace} "
                f"AND {alias}.tenant_id = {self._tenant_expr('t')} "
                f"AND {alias}.identity_key = '' AND {alias}.raw_key = {norm}"
            )
            expression = (
                f"CASE WHEN t.{_quote_identifier(column)} IS NULL THEN NULL "
                f"ELSE {alias}.fake_value END"
            )
            return join, expression

        if rule.strategy in {"fake_name", "fake_phone", "fake_email"}:
            namespace = _sql_literal(rule.namespace)
            norm = _normalise_sql(f"t.{_quote_identifier(column)}", rule.strategy)
            join = (
                f"LEFT JOIN mask_map {alias} ON {alias}.namespace = {namespace} "
                f"AND {alias}.tenant_id = {self._tenant_expr('t')} "
                f"AND {alias}.identity_key = {self._identity_expr(rule.identity)} "
                f"AND {alias}.raw_key = {norm}"
            )
            expression = (
                f"CASE WHEN t.{_quote_identifier(column)} IS NULL THEN NULL "
                f"ELSE {alias}.fake_value END"
            )
            return join, expression

        if rule.strategy == "date_shift":
            join = (
                f"LEFT JOIN date_offsets {alias} ON "
                f"{alias}.tenant_id = {self._tenant_expr('t')} "
                f"AND {alias}.identity_key = {self._identity_expr(rule.identity)}"
            )
            expression = (
                f"CASE WHEN t.{_quote_identifier(column)} IS NULL THEN NULL "
                f"ELSE t.{_quote_identifier(column)} + {alias}.offset_days END"
            )
            return join, expression

        raise MaskingError(f"unsupported mask strategy {rule.strategy} for {table}.{column}")

    def _build_mappings(self) -> None:
        self.con.execute(
            "CREATE TEMP TABLE mask_map ("
            "namespace VARCHAR, tenant_id VARCHAR, identity_key VARCHAR, "
            "raw_key VARCHAR, fake_value VARCHAR)"
        )
        all_rows: list[tuple[str, str, str, str, str]] = []
        for namespace in sorted(self.namespace_specs):
            spec = self.namespace_specs[namespace]
            keys: set[tuple[str, str, str]] = set()
            banned: set[str] = set()
            for table in TABLE_ORDER:
                table_rules = self.rules.tables[table]
                for column, rule in table_rules.columns.items():
                    if rule.namespace != namespace:
                        continue
                    if column not in self.schema.get(table, []):
                        continue
                    source = _quote_identifier("src_" + table)
                    column_sql = _quote_identifier(column)
                    norm = _normalise_sql(column_sql, spec.kind)
                    ban_rows = self.con.execute(
                        f"SELECT DISTINCT {norm} AS value FROM {source} "
                        f"WHERE {column_sql} IS NOT NULL"
                    ).fetchall()
                    banned.update(value for (value,) in ban_rows if value not in (None, ""))

                    if spec.kind == "surrogate_id":
                        rows = self.con.execute(
                            f"SELECT DISTINCT {self._tenant_expr('s')} AS tenant_id, "
                            f"{norm} AS raw_key FROM {source} s WHERE s.{column_sql} IS NOT NULL"
                        ).fetchall()
                        keys.update((tenant, "", raw) for tenant, raw in rows if raw not in (None, ""))
                    else:
                        identity = rule.identity
                        rows = self.con.execute(
                            f"SELECT DISTINCT {self._tenant_expr('s')} AS tenant_id, "
                            f"{self._identity_expr(identity, 's')} AS identity_key, "
                            f"{norm} AS raw_key FROM {source} s "
                            f"WHERE s.{column_sql} IS NOT NULL"
                        ).fetchall()
                        keys.update(
                            (tenant, identity_key, raw)
                            for tenant, identity_key, raw in rows
                            if raw not in (None, "")
                        )

            self.banned_values[namespace] = banned
            try:
                allocation_rows, stats = allocate_namespace(
                    spec,
                    keys,
                    banned,
                    self.seed,
                    self.rule_version,
                    self.rules_hash,
                )
            except AllocationError as exc:
                raise MaskingError(f"映射分配失败：{exc}") from exc
            for row in allocation_rows:
                all_rows.append(
                    (
                        row.namespace,
                        row.tenant_id,
                        row.identity_key,
                        row.raw_key,
                        row.fake_value,
                    )
                )
            self.mapping_stats.append(stats.to_dict())

        if all_rows:
            self.con.executemany(
                "INSERT INTO mask_map VALUES (?, ?, ?, ?, ?)",
                all_rows,
            )

    def _build_offsets(self) -> None:
        identity_columns: dict[str, list[str]] = {}
        for table in TABLE_ORDER:
            identities: set[str] = set()
            for rule in self.rules.tables[table].columns.values():
                if rule.strategy == "date_shift":
                    identities.add(rule.identity)
            identity_columns[table] = sorted(identities)

        keys: set[tuple[str, str]] = set()
        for table in TABLE_ORDER:
            source = _quote_identifier("src_" + table)
            for identity in identity_columns[table]:
                rows = self.con.execute(
                    f"SELECT DISTINCT {self._tenant_expr('s')} AS tenant_id, "
                    f"{self._identity_expr(identity, 's')} AS identity_key FROM {source} s"
                ).fetchall()
                keys.update((tenant, identity_key) for tenant, identity_key in rows)

        self.con.execute(
            "CREATE TEMP TABLE date_offsets ("
            "tenant_id VARCHAR, identity_key VARCHAR, offset_days INTEGER)"
        )
        offset_rows = []
        for tenant, identity in sorted(keys):
            offset = date_offset(
                self.seed,
                self.rule_version,
                self.rules_hash,
                tenant,
                identity,
                self.rules.date_shift.min_days,
                self.rules.date_shift.max_days,
            )
            offset_rows.append((tenant, identity, offset))
        if offset_rows:
            self.con.executemany("INSERT INTO date_offsets VALUES (?, ?, ?)", offset_rows)

        offsets = [row[2] for row in offset_rows]
        by_tenant: dict[str, dict[str, int]] = {}
        for tenant, _, offset in offset_rows:
            bucket = by_tenant.setdefault(
                tenant, {"customers": 0, "min_days": offset, "max_days": offset}
            )
            bucket["customers"] += 1
            bucket["min_days"] = min(bucket["min_days"], offset)
            bucket["max_days"] = max(bucket["max_days"], offset)

        self.offset_stats = {
            "customers": len(offset_rows),
            "min_days": min(offsets) if offsets else 0,
            "max_days": max(offsets) if offsets else 0,
            "distinct_offsets": len(set(offsets)),
            "tenants": by_tenant,
            "configured_range": {
                "min_days": self.rules.date_shift.min_days,
                "max_days": self.rules.date_shift.max_days,
            },
        }

    def _transform(self) -> None:
        for table in TABLE_ORDER:
            source = _quote_identifier("src_" + table)
            output = _quote_identifier("out_" + table)
            table_rules = self.rules.tables[table]
            select_expressions = []
            joins: list[str] = []
            for index, column in enumerate(self.schema[table]):
                rule = table_rules.columns[column]
                column_sql = _quote_identifier(column)
                if rule.strategy == "passthrough":
                    select_expressions.append(f"t.{column_sql} AS {column_sql}")
                elif rule.strategy in MASK_STRATEGIES:
                    join, expression = self._mask_join(table, column, rule, index)
                    joins.append(join)
                    select_expressions.append(f"{expression} AS {column_sql}")
                else:
                    raise MaskingError(f"unsupported strategy {rule.strategy}")
            sql = (
                f"CREATE OR REPLACE TABLE {output} AS SELECT "
                + ", ".join(select_expressions)
                + f" FROM {source} t "
                + " ".join(joins)
            )
            self.con.execute(sql)

    # ------------------------------------------------------------------ helpers
    def replacement_stats(self) -> list[dict]:
        entries = []
        for table in TABLE_ORDER:
            for column, rule in self.rules.tables[table].columns.items():
                if rule.strategy not in MASK_STRATEGIES:
                    continue
                if column not in self.schema.get(table, []):
                    continue
                column_sql = _quote_identifier(column)
                rows, non_null, distinct_values = self.con.execute(
                    f"SELECT COUNT(*), COUNT({column_sql}), COUNT(DISTINCT {column_sql}) "
                    f"FROM {_quote_identifier('out_' + table)}"
                ).fetchone()
                entries.append(
                    {
                        "table": table,
                        "column": column,
                        "strategy": rule.strategy,
                        "strategy_label": STRATEGY_LABELS.get(rule.strategy, rule.strategy),
                        "namespace": rule.namespace,
                        "rows": rows,
                        "replaced": non_null,
                        "preserved_nulls": rows - non_null,
                        "distinct_output_values": distinct_values,
                    }
                )
        return entries

    def mapping_summary(self) -> dict:
        total_values = sum(item["values"] for item in self.mapping_stats)
        total_collisions = sum(item["collisions"] for item in self.mapping_stats)
        total_residual_avoided = sum(item["residual_avoided"] for item in self.mapping_stats)
        return {
            "namespaces": self.mapping_stats,
            "totals": {
                "namespaces": len(self.mapping_stats),
                "values": total_values,
                "collisions": total_collisions,
                "residual_avoided": total_residual_avoided,
            },
        }

    def pk_join(
        self, table: str, source_alias: str = "s", output_alias: str = "o"
    ) -> tuple[list[str], str]:
        """Build joins/condition linking source and output rows by logical primary key."""
        table_rules = self.rules.tables[table]
        joins: list[str] = []
        conditions: list[str] = []
        for index, column in enumerate(table_rules.primary_key):
            rule = table_rules.columns[column]
            column_sql = _quote_identifier(column)
            if rule.strategy == "passthrough":
                conditions.append(f"{output_alias}.{column_sql} = {source_alias}.{column_sql}")
            elif rule.strategy == "surrogate_id":
                alias = f"pk_{index}"
                norm = _normalise_sql(f"{source_alias}.{column_sql}", "surrogate_id")
                joins.append(
                    f"LEFT JOIN mask_map {alias} ON {alias}.namespace = "
                    f"{_sql_literal(rule.namespace)} AND {alias}.tenant_id = "
                    f"{self._tenant_expr(source_alias)} AND {alias}.identity_key = '' "
                    f"AND {alias}.raw_key = {norm}"
                )
                conditions.append(f"{output_alias}.{column_sql} = {alias}.fake_value")
            else:
                raise MaskingError(
                    f"{table}.{column}: unsupported primary key strategy {rule.strategy}"
                )
        return joins, " AND ".join(conditions)

    def _date_offsets_lookup(self) -> dict[tuple[str, str], int]:
        rows = self.con.execute(
            "SELECT tenant_id, identity_key, offset_days FROM date_offsets"
        ).fetchall()
        return {(tenant, identity): offset for tenant, identity, offset in rows}

    # ------------------------------------------------------------------ preview
    def preview(self, limit: int = 5) -> dict:
        self.prepare()
        tables = []
        offsets = self._date_offsets_lookup()
        for table in TABLE_ORDER:
            table_rules = self.rules.tables[table]
            joins, condition = self.pk_join(table, "s", "o")
            select_parts = []
            for column in self.schema[table]:
                column_sql = _quote_identifier(column)
                select_parts.append(f"s.{column_sql} AS {_quote_identifier('raw_' + column)}")
                select_parts.append(f"o.{column_sql} AS {_quote_identifier('out_' + column)}")
            order_by = ", ".join(
                f"s.{_quote_identifier(column)}" for column in table_rules.primary_key
            )
            sql = (
                f"SELECT {', '.join(select_parts)} "
                f"FROM {_quote_identifier('src_' + table)} s "
                + " ".join(joins)
                + f" JOIN {_quote_identifier('out_' + table)} o ON {condition} "
                f"ORDER BY {order_by} LIMIT {int(limit)}"
            )
            cursor = self.con.execute(sql)
            names = [item[0] for item in cursor.description]
            fetched = cursor.fetchall()
            rows = []
            for values in fetched:
                raw = {name: _json_value(value) for name, value in zip(names, values)}
                row = {
                    "cells": {},
                    "meta": {},
                }
                tenant = raw.get(f"raw_{self.rules.tenant_column}")
                for column in self.schema[table]:
                    rule = table_rules.columns[column]
                    raw_value = raw.get(f"raw_{column}")
                    masked_value = raw.get(f"out_{column}")
                    row["cells"][column] = {
                        "raw": raw_value,
                        "masked": masked_value,
                        "changed": raw_value != masked_value,
                        "strategy": rule.strategy,
                        "strategy_label": STRATEGY_LABELS.get(rule.strategy, rule.strategy),
                    }
                identity_columns = {
                    rule.identity
                    for rule in table_rules.columns.values()
                    if rule.strategy == "date_shift" and rule.identity
                }
                if identity_columns:
                    identity = sorted(identity_columns)[0]
                    identity_value = raw.get(f"raw_{identity}") or ""
                    offset = offsets.get((tenant or "", str(identity_value)))
                    row["meta"]["date_offset_days"] = offset
                rows.append(row)

            columns = []
            for column in self.schema[table]:
                rule = table_rules.columns[column]
                columns.append(
                    {
                        "name": column,
                        "strategy": rule.strategy,
                        "strategy_label": STRATEGY_LABELS.get(rule.strategy, rule.strategy),
                        "masked": rule.strategy in MASK_STRATEGIES,
                        "namespace": rule.namespace,
                    }
                )
            row_count = self.con.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier('out_' + table)}"
            ).fetchone()[0]
            tables.append(
                {
                    "name": table,
                    "columns": columns,
                    "rows": rows,
                    "row_count": row_count,
                    "primary_key": table_rules.primary_key,
                    "foreign_keys": [fk.model_dump() for fk in table_rules.foreign_keys],
                }
            )
        return {
            "tables": tables,
            "limit": limit,
            "mapping": self.mapping_summary(),
            "date_shift": self.offset_stats,
            "replacements": self.replacement_stats(),
        }

    # ------------------------------------------------------------------ export
    def export_csvs(self, target_dir: Path) -> list[Path]:
        self.prepare()
        written = []
        for table in TABLE_ORDER:
            path = target_dir / f"{table}.csv"
            self.con.execute(
                f"COPY {_quote_identifier('out_' + table)} TO {_sql_literal(str(path))} "
                "(FORMAT CSV, HEADER, DELIMITER ',')"
            )
            written.append(path)
        return written

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass
