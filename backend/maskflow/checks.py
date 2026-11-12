from __future__ import annotations

import hashlib
import json
from typing import Any

from .engine import MaskingEngine, _normalise_sql, _quote_identifier
from .rules import MASK_STRATEGIES
from .schema import TABLE_ORDER

SUBSTRING_RESIDUAL_KINDS = {"fake_phone", "fake_email"}


def _fetch(engine: MaskingEngine, sql: str) -> list[tuple]:
    return engine.con.execute(sql).fetchall()


def _one(engine: MaskingEngine, sql: str) -> Any:
    return engine.con.execute(sql).fetchone()[0]


def _table(name: str, prefix: str = "out_") -> str:
    return _quote_identifier(prefix + name)


def _signature(rows: list[tuple]) -> str:
    payload = json.dumps(rows, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def check_primary_keys(engine: MaskingEngine) -> list[dict]:
    results = []
    for table in TABLE_ORDER:
        table_rules = engine.rules.tables[table]
        pk = table_rules.primary_key
        pk_sql = ", ".join(_quote_identifier(column) for column in pk)
        rows = _one(engine, f"SELECT COUNT(*) FROM {_table(table)}")
        duplicates = _one(
            engine,
            f"SELECT COUNT(*) FROM (SELECT {pk_sql} FROM {_table(table)} "
            f"GROUP BY {pk_sql} HAVING COUNT(*) > 1)",
        )
        null_condition = " OR ".join(
            f"{_quote_identifier(column)} IS NULL" for column in pk
        )
        null_keys = _one(
            engine, f"SELECT COUNT(*) FROM {_table(table)} WHERE {null_condition}"
        )
        results.append(
            {
                "table": table,
                "columns": pk,
                "rows": rows,
                "duplicate_keys": duplicates,
                "null_keys": null_keys,
                "passed": duplicates == 0 and null_keys == 0,
            }
        )
    return results


def check_foreign_keys(engine: MaskingEngine) -> list[dict]:
    results = []
    for table in TABLE_ORDER:
        table_rules = engine.rules.tables[table]
        for fk in table_rules.foreign_keys:
            parent_table = fk.references.table
            parent_columns = fk.references.columns
            conditions = " AND ".join(
                f"p.{_quote_identifier(parent)} = c.{_quote_identifier(child)}"
                for child, parent in zip(fk.columns, parent_columns)
            )
            checked = _one(engine, f"SELECT COUNT(*) FROM {_table(table)} c")
            violations = _one(
                engine,
                f"SELECT COUNT(*) FROM {_table(table)} c WHERE NOT EXISTS "
                f"(SELECT 1 FROM {_table(parent_table)} p WHERE {conditions})",
            )
            results.append(
                {
                    "table": table,
                    "columns": fk.columns,
                    "references": f"{parent_table}.{parent_columns}",
                    "checked": checked,
                    "violations": violations,
                    "passed": violations == 0,
                }
            )
    return results


def check_row_counts(engine: MaskingEngine) -> list[dict]:
    results = []
    for table in TABLE_ORDER:
        source_rows = _one(engine, f"SELECT COUNT(*) FROM {_table(table, 'src_')}")
        output_rows = _one(engine, f"SELECT COUNT(*) FROM {_table(table)}")
        results.append(
            {
                "table": table,
                "source_rows": source_rows,
                "output_rows": output_rows,
                "passed": source_rows == output_rows,
            }
        )
    return results


def check_null_preservation(engine: MaskingEngine) -> list[dict]:
    results = []
    for table in TABLE_ORDER:
        table_rules = engine.rules.tables[table]
        joins, condition = engine.pk_join(table, "s", "o")
        for column, rule in table_rules.columns.items():
            if rule.strategy not in MASK_STRATEGIES:
                continue
            column_sql = _quote_identifier(column)
            source_null = _one(
                engine,
                f"SELECT COUNT(*) FROM {_table(table, 'src_')} WHERE {column_sql} IS NULL",
            )
            output_null = _one(
                engine,
                f"SELECT COUNT(*) FROM {_table(table)} WHERE {column_sql} IS NULL",
            )
            lost = _one(
                engine,
                f"SELECT COUNT(*) FROM {_table(table, 'src_')} s "
                f"{(' '.join(joins))} JOIN {_table(table)} o ON {condition} "
                f"WHERE s.{column_sql} IS NOT NULL AND o.{column_sql} IS NULL",
            )
            results.append(
                {
                    "table": table,
                    "column": column,
                    "strategy": rule.strategy,
                    "source_nulls": source_null,
                    "output_nulls": output_null,
                    "non_null_to_null": lost,
                    "passed": source_null == output_null and lost == 0,
                }
            )
    return results


def check_date_shift(engine: MaskingEngine) -> tuple[dict, list[dict]]:
    column_checks = []
    for table in TABLE_ORDER:
        table_rules = engine.rules.tables[table]
        joins, condition = engine.pk_join(table, "s", "o")
        for column, rule in table_rules.columns.items():
            if rule.strategy != "date_shift":
                continue
            column_sql = _quote_identifier(column)
            identity = rule.identity
            tenant_expr = engine._tenant_expr("s")
            identity_expr = engine._identity_expr(identity, "s")
            lost, invented, inconsistent = engine.con.execute(
                f"SELECT "
                f"COUNT(*) FILTER (WHERE s.{column_sql} IS NOT NULL AND o.{column_sql} IS NULL), "
                f"COUNT(*) FILTER (WHERE s.{column_sql} IS NULL AND o.{column_sql} IS NOT NULL), "
                f"COUNT(*) FILTER (WHERE s.{column_sql} IS NOT NULL AND o.{column_sql} IS NOT NULL "
                f"AND date_diff('day', s.{column_sql}, o.{column_sql}) <> off.offset_days) "
                f"FROM {_table(table, 'src_')} s {(' '.join(joins))} "
                f"JOIN {_table(table)} o ON {condition} "
                f"JOIN date_offsets off ON off.tenant_id = {tenant_expr} "
                f"AND off.identity_key = {identity_expr}"
            ).fetchone()
            column_checks.append(
                {
                    "table": table,
                    "column": column,
                    "identity": identity,
                    "non_null_to_null": lost,
                    "null_to_non_null": invented,
                    "offset_violations": inconsistent,
                    "passed": lost == 0 and invented == 0 and inconsistent == 0,
                }
            )

    configured = engine.rules.date_shift
    summary = dict(engine.offset_stats)
    summary["configured_range"] = {
        "min_days": configured.min_days,
        "max_days": configured.max_days,
    }
    range_ok = (
        summary["min_days"] >= configured.min_days
        and summary["max_days"] <= configured.max_days
    )
    summary["range_ok"] = range_ok
    summary["passed"] = range_ok and all(item["passed"] for item in column_checks)
    return summary, column_checks


def check_date_invariants(engine: MaskingEngine) -> list[dict]:
    results = []
    for invariant in engine.rules.invariants:
        left = _quote_identifier(invariant.left)
        right = _quote_identifier(invariant.right)
        checked, violations = engine.con.execute(
            f"SELECT COUNT(*) FILTER (WHERE {left} IS NOT NULL AND {right} IS NOT NULL), "
            f"COUNT(*) FILTER (WHERE {left} IS NOT NULL AND {right} IS NOT NULL "
            f"AND NOT ({left} <= {right})) "
            f"FROM {_table(invariant.table)}"
        ).fetchone()
        results.append(
            {
                "table": invariant.table,
                "left": invariant.left,
                "right": invariant.right,
                "description": invariant.description
                or f"{invariant.left} <= {invariant.right}",
                "checked": checked,
                "violations": violations,
                "passed": violations == 0,
            }
        )
    return results


def check_interval_preservation(engine: MaskingEngine) -> list[dict]:
    """Offsets cancel, so every event interval must be byte-for-byte equal."""
    results = []
    for invariant in engine.rules.invariants:
        table = invariant.table
        joins, condition = engine.pk_join(table, "s", "o")
        left = _quote_identifier(invariant.left)
        right = _quote_identifier(invariant.right)
        checked, mismatched = engine.con.execute(
            f"SELECT COUNT(*), COUNT(*) FILTER (WHERE "
            f"date_diff('day', s.{left}, s.{right}) <> "
            f"date_diff('day', o.{left}, o.{right})) "
            f"FROM {_table(table, 'src_')} s {(' '.join(joins))} "
            f"JOIN {_table(table)} o ON {condition} "
            f"WHERE s.{left} IS NOT NULL AND s.{right} IS NOT NULL"
        ).fetchone()
        results.append(
            {
                "table": table,
                "interval": f"{invariant.left} -> {invariant.right}",
                "checked": checked,
                "mismatched": mismatched,
                "passed": mismatched == 0,
            }
        )
    return results


def check_sequences(engine: MaskingEngine) -> list[dict]:
    """Event ordering per customer must survive the shift."""
    results = []
    for table in TABLE_ORDER:
        table_rules = engine.rules.tables[table]
        date_rules = [
            (column, rule)
            for column, rule in table_rules.columns.items()
            if rule.strategy == "date_shift" and rule.identity
        ]
        if not date_rules or table not in {"orders", "after_sales"}:
            continue
        event_keys = [
            column
            for column in table_rules.primary_key
            if table_rules.columns[column].strategy == "passthrough"
            and column != engine.rules.tenant_column
        ]
        if not event_keys:
            continue
        event = next(
            (column for column in ("order_id", "case_id") if column in table_rules.primary_key),
            event_keys[0],
        )
        date_column = date_rules[0][0]
        identity = date_rules[0][1].identity
        tenant = engine.rules.tenant_column
        join_condition = " AND ".join(
            f"sv.{_quote_identifier(tenant)} = ov.{_quote_identifier(tenant)} "
            f"AND sv.{_quote_identifier(event)} = ov.{_quote_identifier(event)}"
            for _ in [0]
        )
        mismatched = _one(
            engine,
            f"WITH sv AS (SELECT {_quote_identifier(tenant)}, "
            f"{_quote_identifier(identity)}, {_quote_identifier(event)}, "
            f"row_number() OVER (PARTITION BY {_quote_identifier(tenant)}, "
            f"{_quote_identifier(identity)} ORDER BY {_quote_identifier(date_column)}, "
            f"{_quote_identifier(event)}) AS rn FROM {_table(table, 'src_')}), "
            f"ov AS (SELECT {_quote_identifier(tenant)}, "
            f"{_quote_identifier(identity)}, {_quote_identifier(event)}, "
            f"row_number() OVER (PARTITION BY {_quote_identifier(tenant)}, "
            f"{_quote_identifier(identity)} ORDER BY {_quote_identifier(date_column)}, "
            f"{_quote_identifier(event)}) AS rn FROM {_table(table)}) "
            f"SELECT COUNT(*) FROM sv JOIN ov ON {join_condition} "
            f"WHERE sv.rn <> ov.rn",
        )
        checked = _one(engine, f"SELECT COUNT(*) FROM {_table(table)}")
        results.append(
            {
                "table": table,
                "event_key": event,
                "order_by": [date_column, event],
                "checked": checked,
                "mismatched": mismatched,
                "passed": mismatched == 0,
            }
        )
    return results


def check_residual_values(engine: MaskingEngine) -> list[dict]:
    engine.con.execute(
        "CREATE OR REPLACE TEMP TABLE banned_values (namespace VARCHAR, value VARCHAR)"
    )
    rows = [
        (namespace, value)
        for namespace, values in sorted(engine.banned_values.items())
        for value in sorted(values)
    ]
    if rows:
        engine.con.executemany("INSERT INTO banned_values VALUES (?, ?)", rows)

    results = []
    for namespace in sorted(engine.banned_values):
        spec = engine.namespace_specs[namespace]
        columns = [
            (table, column, rule)
            for table in TABLE_ORDER
            for column, rule in engine.rules.tables[table].columns.items()
            if rule.namespace == namespace and rule.strategy in MASK_STRATEGIES
        ]
        exact_hits = 0
        substring_hits = 0
        for table, column, rule in columns:
            column_sql = _quote_identifier(column)
            norm = _normalise_sql(column_sql, spec.kind)
            exact_hits += _one(
                engine,
                f"SELECT COUNT(*) FROM {_table(table)} WHERE {norm} IN "
                f"(SELECT value FROM banned_values WHERE namespace = "
                f"'{namespace.replace(chr(39), chr(39) * 2)}')",
            )
            if spec.kind in SUBSTRING_RESIDUAL_KINDS:
                substring_hits += _one(
                    engine,
                    f"SELECT COUNT(*) FROM {_table(table)} WHERE EXISTS "
                    f"(SELECT 1 FROM banned_values b WHERE b.namespace = "
                    f"'{namespace.replace(chr(39), chr(39) * 2)}' "
                    f"AND strpos(CAST({column_sql} AS VARCHAR), b.value) > 0)",
                )
        results.append(
            {
                "namespace": namespace,
                "kind": spec.kind,
                "original_values": len(engine.banned_values[namespace]),
                "masked_columns": len(columns),
                "exact_hits": exact_hits,
                "substring_hits": substring_hits,
                "mode": "exact+substring" if spec.kind in SUBSTRING_RESIDUAL_KINDS else "exact",
                "passed": exact_hits == 0 and substring_hits == 0,
            }
        )
    return results


def _business_queries(prefix: str) -> list[tuple[str, str, str]]:
    orders = _quote_identifier(prefix + "orders")
    customers = _quote_identifier(prefix + "customers")
    after_sales = _quote_identifier(prefix + "after_sales")
    return [
        (
            "orders_per_customer",
            "跨表关联：每位客户的订单数分布",
            "SELECT tenant_id, cnt FROM (SELECT o.tenant_id, COUNT(*) AS cnt "
            f"FROM {orders} o JOIN {customers} c ON c.tenant_id = o.tenant_id "
            "AND c.customer_id = o.customer_id GROUP BY o.tenant_id, o.customer_id) "
            "ORDER BY tenant_id, cnt",
        ),
        (
            "revenue_by_status",
            "聚合：各租户各订单状态的销售额",
            "SELECT tenant_id, status, CAST(SUM(amount) AS VARCHAR) "
            f"FROM {orders} GROUP BY tenant_id, status ORDER BY tenant_id, status",
        ),
        (
            "after_sales_per_order",
            "关联：每个订单关联的售后单数",
            "SELECT tenant_id, order_id, COUNT(*) "
            f"FROM {after_sales} GROUP BY tenant_id, order_id ORDER BY tenant_id, order_id",
        ),
        (
            "order_amounts",
            f"明细：订单金额（{prefix.rstrip('_')}）",
            "SELECT tenant_id, order_id, CAST(amount AS VARCHAR) "
            f"FROM {orders} ORDER BY tenant_id, order_id",
        ),
        (
            "repeat_customers",
            "留存：复购客户数量",
            "SELECT tenant_id, COUNT(*) FROM (SELECT tenant_id, customer_id, COUNT(*) AS cnt "
            f"FROM {orders} GROUP BY tenant_id, customer_id HAVING COUNT(*) >= 2) "
            "GROUP BY tenant_id ORDER BY tenant_id",
        ),
    ]


def check_business_queries(engine: MaskingEngine) -> list[dict]:
    results = []
    for query_id, description, sql in _business_queries("src_"):
        source_rows = _fetch(engine, sql)
        masked_sql = sql.replace("src_", "out_")
        masked_rows = _fetch(engine, masked_sql)
        results.append(
            {
                "id": query_id,
                "description": description,
                "source_signature": _signature(source_rows),
                "masked_signature": _signature(masked_rows),
                "source_groups": len(source_rows),
                "masked_groups": len(masked_rows),
                "passed": source_rows == masked_rows,
            }
        )
    return results


def run_checks(engine: MaskingEngine) -> dict:
    engine.prepare()
    primary_keys = check_primary_keys(engine)
    foreign_keys = check_foreign_keys(engine)
    row_counts = check_row_counts(engine)
    null_preservation = check_null_preservation(engine)
    date_summary, date_columns = check_date_shift(engine)
    date_invariants = check_date_invariants(engine)
    intervals = check_interval_preservation(engine)
    sequences = check_sequences(engine)
    residual = check_residual_values(engine)
    business_queries = check_business_queries(engine)

    sections = {
        "primary_keys": primary_keys,
        "foreign_keys": foreign_keys,
        "row_counts": row_counts,
        "null_preservation": null_preservation,
        "date_shift_columns": date_columns,
        "date_invariants": date_invariants,
        "intervals": intervals,
        "sequences": sequences,
        "residual": residual,
        "business_queries": business_queries,
    }
    failures = []
    for name, items in sections.items():
        if not all(item.get("passed", False) for item in items):
            failures.append(name)
    if not date_summary.get("passed", False):
        failures.append("date_shift")
    checks = {
        **sections,
        "date_shift": date_summary,
        "passed": not failures,
        "blocking_failures": failures,
    }
    return checks
