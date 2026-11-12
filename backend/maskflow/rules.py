from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .schema import DEFAULT_RULES, PHONE_PREFIXES

Strategy = Literal[
    "passthrough",
    "surrogate_id",
    "fake_name",
    "fake_phone",
    "fake_email",
    "date_shift",
]

MASK_STRATEGIES = {"surrogate_id", "fake_name", "fake_phone", "fake_email", "date_shift"}
ID_STRATEGIES = {"surrogate_id"}
DEFAULT_MAX_LENGTH = {
    "surrogate_id": 12,
    "fake_phone": 11,
    "fake_email": 40,
    "fake_name": 8,
}
DEFAULT_EMAIL_DOMAIN = "masked.example"


class ColumnRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Strategy
    namespace: str | None = None
    identity: str | None = None
    max_length: int | None = Field(default=None, ge=1, le=512)
    prefix: str | None = None
    prefixes: list[str] | None = None
    domain: str | None = None


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str
    columns: list[str]


class ForeignKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str]
    references: Reference


class TableRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_key: list[str]
    foreign_keys: list[ForeignKey] = Field(default_factory=list)
    columns: dict[str, ColumnRule]


class DateShiftConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_days: int = Field(default=-30, ge=-3650, le=3650)
    max_days: int = Field(default=30, ge=-3650, le=3650)


class DateInvariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str
    left: str
    right: str
    description: str = ""


class Ruleset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=64)
    tenant_column: str = "tenant_id"
    date_shift: DateShiftConfig = Field(default_factory=DateShiftConfig)
    tables: dict[str, TableRules]
    invariants: list[DateInvariant] = Field(default_factory=list)


@dataclass(frozen=True)
class NamespaceSpec:
    namespace: str
    kind: str
    max_length: int
    prefix: str = ""
    prefixes: tuple[str, ...] = ()
    domain: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuleReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    rules_hash: str = ""

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "coverage": self.coverage,
            "rules_hash": self.rules_hash,
        }


def effective_spec(rule: ColumnRule) -> NamespaceSpec:
    assert rule.namespace is not None
    max_length = rule.max_length or DEFAULT_MAX_LENGTH[rule.strategy]
    if rule.strategy == "surrogate_id":
        return NamespaceSpec(
            namespace=rule.namespace,
            kind=rule.strategy,
            max_length=max_length,
            prefix=rule.prefix or "",
        )
    if rule.strategy == "fake_phone":
        return NamespaceSpec(
            namespace=rule.namespace,
            kind=rule.strategy,
            max_length=max_length,
            prefixes=tuple(rule.prefixes or PHONE_PREFIXES),
        )
    if rule.strategy == "fake_email":
        return NamespaceSpec(
            namespace=rule.namespace,
            kind=rule.strategy,
            max_length=max_length,
            domain=rule.domain or DEFAULT_EMAIL_DOMAIN,
        )
    if rule.strategy == "fake_name":
        return NamespaceSpec(namespace=rule.namespace, kind=rule.strategy, max_length=max_length)
    raise ValueError(f"strategy {rule.strategy} has no namespace spec")


def collect_namespaces(rules: Ruleset) -> tuple[dict[str, NamespaceSpec], list[str]]:
    specs: dict[str, NamespaceSpec] = {}
    usage: dict[str, list[tuple[str, str]]] = {}
    errors: list[str] = []

    for table_name, table in rules.tables.items():
        for column_name, rule in table.columns.items():
            if rule.strategy not in {"surrogate_id", "fake_name", "fake_phone", "fake_email"}:
                continue
            if not rule.namespace:
                errors.append(f"{table_name}.{column_name}: namespace 不能为空")
                continue
            spec = effective_spec(rule)
            existing = specs.get(rule.namespace)
            if existing is None:
                specs[rule.namespace] = spec
            elif existing != spec:
                errors.append(
                    f"命名空间 {rule.namespace} 的生成参数不一致："
                    f"{existing.kind}/{existing.max_length} 与 "
                    f"{spec.kind}/{spec.max_length}"
                )
            usage.setdefault(rule.namespace, []).append((table_name, column_name))

    for namespace, columns in usage.items():
        if specs.get(namespace) and specs[namespace].kind == "surrogate_id":
            names = {column for _, column in columns}
            if len(names) > 1:
                errors.append(
                    f"命名空间 {namespace} 被多个不同列名的代理编号共用："
                    + "、".join(sorted(names))
                )

    identity_usage: dict[str, set[str]] = {}
    for table_name, table in rules.tables.items():
        for column_name, rule in table.columns.items():
            if rule.namespace in specs and rule.strategy in {
                "fake_name",
                "fake_phone",
                "fake_email",
            }:
                identity_usage.setdefault(rule.namespace, set()).add(rule.identity or "")
    for namespace, identities in identity_usage.items():
        if len(identities) > 1:
            errors.append(
                f"命名空间 {namespace} 使用了多个身份列："
                + "、".join(sorted(identities))
            )
    return specs, errors


def canonical_rules_json(rules: Ruleset) -> str:
    return json.dumps(
        rules.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def rules_hash(rules: Ruleset) -> str:
    return hashlib.sha256(canonical_rules_json(rules).encode("utf-8")).hexdigest()[:16]


def parse_rules(payload: Any) -> tuple[Ruleset | None, RuleReport]:
    report = RuleReport()
    if not isinstance(payload, dict):
        report.errors.append("规则必须是 JSON 对象")
        return None, report
    try:
        rules = Ruleset.model_validate(payload)
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            report.errors.append(f"{location or 'rules'}: {error['msg']}")
        return None, report
    report.rules_hash = rules_hash(rules)
    return rules, report


def validate_rules(rules: Ruleset, schema: dict[str, list[str]]) -> RuleReport:
    report = RuleReport(rules_hash=rules_hash(rules))
    table_names = set(schema)
    rule_tables = set(rules.tables)

    for name in sorted(table_names - rule_tables):
        report.errors.append(f"缺少表的脱敏规则：{name}")
    for name in sorted(rule_tables - table_names):
        report.errors.append(f"规则引用了不存在的数据表：{name}")

    masked_columns = 0
    total_columns = 0

    for table_name in sorted(table_names & rule_tables):
        actual_columns = schema[table_name]
        table = rules.tables[table_name]
        total_columns += len(actual_columns)

        unknown = sorted(set(table.columns) - set(actual_columns))
        missing = sorted(set(actual_columns) - set(table.columns))
        for column in unknown:
            report.errors.append(f"{table_name}.{column}: 数据表中不存在该列")
        for column in missing:
            report.errors.append(f"{table_name}.{column}: 缺少脱敏规则")

        tenant_column = rules.tenant_column
        if tenant_column not in table.columns:
            report.errors.append(f"{table_name}: 租户列 {tenant_column} 缺少规则")

        if not table.primary_key:
            report.errors.append(f"{table_name}: 主键不能为空")
        for pk_column in table.primary_key:
            if pk_column not in actual_columns:
                report.errors.append(f"{table_name}.{pk_column}: 主键列不存在")
                continue
            if pk_column not in table.columns:
                continue
            strategy = table.columns[pk_column].strategy
            if strategy not in {"passthrough", "surrogate_id"}:
                report.errors.append(
                    f"{table_name}.{pk_column}: 主键列只能使用 passthrough 或 surrogate_id"
                )

        for fk in table.foreign_keys:
            if len(fk.columns) == 0:
                report.errors.append(f"{table_name}: 外键列不能为空")
                continue
            for column in fk.columns:
                if column not in actual_columns:
                    report.errors.append(f"{table_name}.{column}: 外键列不存在")
            reference_columns = fk.references.columns
            reference_table = fk.references.table
            if len(fk.columns) != len(reference_columns):
                report.errors.append(f"{table_name}: 外键列数量与引用列数量不一致")
                continue
            if reference_table not in schema:
                report.errors.append(f"{table_name}: 外键引用了不存在的表 {reference_table}")
                continue
            if reference_table not in rules.tables:
                report.errors.append(f"{table_name}: 外键引用的表 {reference_table} 缺少规则")
                continue
            parent = rules.tables[reference_table]
            if reference_columns != parent.primary_key:
                report.errors.append(
                    f"{table_name}: 外键必须引用父表 {reference_table} 的完整主键 "
                    f"{parent.primary_key}"
                )
            for position, (child_column, parent_column) in enumerate(
                zip(fk.columns, reference_columns)
            ):
                if child_column not in table.columns or parent_column not in parent.columns:
                    continue
                child_rule = table.columns[child_column]
                parent_rule = parent.columns[parent_column]
                if child_rule.strategy != parent_rule.strategy:
                    report.errors.append(
                        f"{table_name}.{child_column} -> {reference_table}.{parent_column}: "
                        f"外键与主键的脱敏策略不一致 "
                        f"({child_rule.strategy} vs {parent_rule.strategy})"
                    )
                elif child_rule.strategy == "surrogate_id":
                    if child_rule.namespace != parent_rule.namespace:
                        report.errors.append(
                            f"{table_name}.{child_column} -> {reference_table}.{parent_column}: "
                            "代理编号命名空间不一致"
                        )

        for column_name, rule in table.columns.items():
            if column_name not in actual_columns:
                continue
            if rule.strategy in MASK_STRATEGIES:
                masked_columns += 1

            if rule.strategy == "surrogate_id":
                if not rule.namespace:
                    report.errors.append(f"{table_name}.{column_name}: surrogate_id 需要 namespace")
                prefix = rule.prefix or ""
                length = rule.max_length or DEFAULT_MAX_LENGTH[rule.strategy]
                if length - len(prefix) < 4:
                    report.errors.append(
                        f"{table_name}.{column_name}: max_length 扣除前缀后至少需要 4 位"
                    )

            if rule.strategy in {"fake_name", "fake_phone", "fake_email", "date_shift"}:
                if not rule.identity:
                    report.errors.append(f"{table_name}.{column_name}: 需要 identity 列")
                elif rule.identity not in actual_columns:
                    report.errors.append(
                        f"{table_name}.{column_name}: identity 列 {rule.identity} 不存在"
                    )

            if rule.strategy == "fake_phone":
                length = rule.max_length or DEFAULT_MAX_LENGTH[rule.strategy]
                prefixes = rule.prefixes or PHONE_PREFIXES
                if not prefixes:
                    report.errors.append(f"{table_name}.{column_name}: 至少需要一个手机号前缀")
                for prefix in prefixes:
                    if not prefix.isdigit():
                        report.errors.append(
                            f"{table_name}.{column_name}: 手机号前缀必须为数字：{prefix}"
                        )
                    if len(prefix) > length:
                        report.errors.append(
                            f"{table_name}.{column_name}: 手机号前缀 {prefix} 超过 max_length"
                        )

            if rule.strategy == "fake_email":
                length = rule.max_length or DEFAULT_MAX_LENGTH[rule.strategy]
                domain = rule.domain or DEFAULT_EMAIL_DOMAIN
                if "@" in domain or not domain:
                    report.errors.append(f"{table_name}.{column_name}: 邮箱域名格式不正确")
                if length < len(domain) + 2:
                    report.errors.append(
                        f"{table_name}.{column_name}: max_length 太短，无法容纳邮箱域名"
                    )

    namespace_specs, namespace_errors = collect_namespaces(rules)
    report.errors.extend(namespace_errors)

    has_date_shift = any(
        rule.strategy == "date_shift"
        for table in rules.tables.values()
        for rule in table.columns.values()
    )
    if has_date_shift:
        if rules.date_shift.min_days > rules.date_shift.max_days:
            report.errors.append("date_shift: min_days 不能大于 max_days")
        span = rules.date_shift.max_days - rules.date_shift.min_days
        if span > 3660:
            report.warnings.append("date_shift: 平移范围超过 10 年，请确认业务含义")

    for invariant in rules.invariants:
        if invariant.table not in rules.tables:
            report.errors.append(f"invariant: 表 {invariant.table} 不存在")
            continue
        table = rules.tables[invariant.table]
        for column in (invariant.left, invariant.right):
            if column not in table.columns:
                report.errors.append(f"invariant: 列 {invariant.table}.{column} 不存在")
            elif table.columns[column].strategy not in {"date_shift", "passthrough"}:
                report.warnings.append(
                    f"invariant: {invariant.table}.{column} 不是日期列，比较可能不可靠"
                )

    for table_name, table in rules.tables.items():
        tenant_rule = table.columns.get(rules.tenant_column)
        if tenant_rule and tenant_rule.strategy != "passthrough":
            report.warnings.append(
                f"{table_name}: 租户列 {rules.tenant_column} 被脱敏，租户隔离仍按原值生效"
            )

    report.coverage = {
        "tables": len(table_names & rule_tables),
        "columns": total_columns,
        "masked_columns": masked_columns,
        "namespaces": sorted(namespace_specs),
        "date_shift": has_date_shift,
    }
    return report


def load_default_rules() -> Ruleset:
    return Ruleset.model_validate(DEFAULT_RULES)
