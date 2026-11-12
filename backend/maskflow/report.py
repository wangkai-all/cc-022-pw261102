from __future__ import annotations

from typing import Any


def _status(passed: bool) -> str:
    return "通过" if passed else "失败"


def build_report(
    *,
    job_id: str,
    created_at: str,
    rule_version: str,
    rules_hash: str,
    seed_source: str,
    replacements: list[dict],
    mapping: dict,
    date_shift: dict,
    checks: dict,
    files: list[dict],
    content_fingerprint: str,
    source_rows: dict[str, int],
) -> dict[str, Any]:
    totals = {
        "tables": len(source_rows),
        "source_rows": sum(source_rows.values()),
        "replaced_values": sum(item["replaced"] for item in replacements),
        "distinct_mapping_values": mapping["totals"]["values"],
        "collisions": mapping["totals"]["collisions"],
        "residual_hits": sum(
            item["exact_hits"] + item["substring_hits"] for item in checks["residual"]
        ),
        "checks_passed": checks["passed"],
    }
    return {
        "job_id": job_id,
        "created_at": created_at,
        "rule_version": rule_version,
        "rules_hash": rules_hash,
        "deterministic": {
            "rule_version": rule_version,
            "rules_hash": rules_hash,
            "seed_configuration": seed_source,
            "note": "种子值不会写入导出文件；同一规则版本与同一种子可复现相同内容",
        },
        "totals": totals,
        "source_rows": source_rows,
        "replacements": replacements,
        "mapping": mapping,
        "date_shift": date_shift,
        "checks": checks,
        "files": files,
        "content_fingerprint": content_fingerprint,
    }


def render_markdown(report: dict[str, Any]) -> str:
    checks = report["checks"]
    mapping = report["mapping"]
    date_shift = report["date_shift"]
    lines: list[str] = []
    lines.append("# MaskFlow 脱敏生成报告")
    lines.append("")
    lines.append(f"- 任务编号：`{report['job_id']}`")
    lines.append(f"- 生成时间：{report['created_at']}")
    lines.append(f"- 规则版本：`{report['rule_version']}`")
    lines.append(f"- 规则指纹：`{report['rules_hash']}`")
    lines.append(f"- 内容指纹：`{report['content_fingerprint']}`")
    lines.append(f"- 种子来源：{report['deterministic']['seed_configuration']}（种子值未写入导出文件）")
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    lines.append(f"- 发布状态：{'通过，已原子发布' if checks['passed'] else '失败，未发布任何文件'}")
    lines.append(f"- 源数据行数：{report['totals']['source_rows']}")
    lines.append(f"- 替换值数量：{report['totals']['replaced_values']}")
    lines.append(f"- 映射值数量：{report['totals']['distinct_mapping_values']}")
    lines.append(f"- 碰撞次数：{report['totals']['collisions']}")
    lines.append(f"- 原敏感值残留：{report['totals']['residual_hits']}")
    lines.append("")

    lines.append("## 替换数量")
    lines.append("")
    lines.append("| 表 | 列 | 策略 | 替换数量 | 保留空值 | 输出去重值 |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: |")
    for item in report["replacements"]:
        lines.append(
            f"| {item['table']} | {item['column']} | {item['strategy_label']} "
            f"| {item['replaced']} | {item['preserved_nulls']} "
            f"| {item['distinct_output_values']} |"
        )
    lines.append("")

    lines.append("## 碰撞处理")
    lines.append("")
    lines.append("| 命名空间 | 类型 | 租户 | 分配值 | 碰撞次数 | 残留规避 | 最大尝试 |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: |")
    for namespace in mapping["namespaces"]:
        if not namespace["tenants"]:
            lines.append(
                f"| {namespace['namespace']} | {namespace['kind']} | - | "
                f"{namespace['values']} | {namespace['collisions']} | "
                f"{namespace['residual_avoided']} | {namespace['max_attempts']} |"
            )
        for tenant, stats in sorted(namespace["tenants"].items()):
            lines.append(
                f"| {namespace['namespace']} | {namespace['kind']} | {tenant} | "
                f"{stats['values']} | {stats['collisions']} | "
                f"{stats['residual_avoided']} | {namespace['max_attempts']} |"
            )
    lines.append("")
    lines.append(
        "碰撞通过确定性二次探测解决；原值集合被预先加入禁用集合，"
        "因此生成值不会与任何原始敏感值相同。"
    )
    lines.append("")

    lines.append("## 关联与完整性校验")
    lines.append("")
    lines.append("### 主键唯一")
    lines.append("")
    lines.append("| 表 | 主键 | 行数 | 重复键 | 空键 | 结果 |")
    lines.append("| --- | --- | ---: | ---: | ---: | --- |")
    for item in checks["primary_keys"]:
        lines.append(
            f"| {item['table']} | {', '.join(item['columns'])} | {item['rows']} | "
            f"{item['duplicate_keys']} | {item['null_keys']} | {_status(item['passed'])} |"
        )
    lines.append("")
    lines.append("### 外键完整")
    lines.append("")
    lines.append("| 子表 | 外键列 | 引用 | 检查行数 | 违规 | 结果 |")
    lines.append("| --- | --- | --- | ---: | ---: | --- |")
    for item in checks["foreign_keys"]:
        lines.append(
            f"| {item['table']} | {', '.join(item['columns'])} | {item['references']} | "
            f"{item['checked']} | {item['violations']} | {_status(item['passed'])} |"
        )
    lines.append("")
    lines.append("### 行数与空值")
    lines.append("")
    lines.append("| 表 | 源行数 | 输出行数 | 结果 |")
    lines.append("| --- | ---: | ---: | --- |")
    for item in checks["row_counts"]:
        lines.append(
            f"| {item['table']} | {item['source_rows']} | {item['output_rows']} | "
            f"{_status(item['passed'])} |"
        )
    lines.append("")
    lines.append("| 表.列 | 源空值 | 输出空值 | 非空变空 | 结果 |")
    lines.append("| --- | ---: | ---: | ---: | --- |")
    for item in checks["null_preservation"]:
        lines.append(
            f"| {item['table']}.{item['column']} | {item['source_nulls']} | "
            f"{item['output_nulls']} | {item['non_null_to_null']} | "
            f"{_status(item['passed'])} |"
        )
    lines.append("")

    lines.append("## 日期整体平移")
    lines.append("")
    lines.append(
        f"- 平移客户数：{date_shift['customers']}；偏移范围："
        f"{date_shift['min_days']} ~ {date_shift['max_days']} 天；"
        f"不同偏移：{date_shift['distinct_offsets']} 种"
    )
    configured = date_shift["configured_range"]
    lines.append(
        f"- 配置范围：{configured['min_days']} ~ {configured['max_days']} 天；"
        f"范围检查：{_status(date_shift['range_ok'])}"
    )
    lines.append("")
    lines.append("| 表.日期列 | 身份列 | 非空变空 | 空变非空 | 偏移不一致 | 结果 |")
    lines.append("| --- | --- | ---: | ---: | ---: | --- |")
    for item in checks["date_shift_columns"]:
        lines.append(
            f"| {item['table']}.{item['column']} | {item['identity']} | "
            f"{item['non_null_to_null']} | {item['null_to_non_null']} | "
            f"{item['offset_violations']} | {_status(item['passed'])} |"
        )
    lines.append("")
    lines.append("| 表 | 先后约束 | 检查行数 | 违规 | 结果 |")
    lines.append("| --- | --- | ---: | ---: | --- |")
    for item in checks["date_invariants"]:
        lines.append(
            f"| {item['table']} | {item['description']} | {item['checked']} | "
            f"{item['violations']} | {_status(item['passed'])} |"
        )
    lines.append("")
    lines.append("| 表 | 间隔 | 检查行数 | 间隔变化 | 结果 |")
    lines.append("| --- | --- | ---: | ---: | --- |")
    for item in checks["intervals"]:
        lines.append(
            f"| {item['table']} | {item['interval']} | {item['checked']} | "
            f"{item['mismatched']} | {_status(item['passed'])} |"
        )
    lines.append("")
    lines.append("| 表 | 事件键 | 排序依据 | 检查行数 | 次序变化 | 结果 |")
    lines.append("| --- | --- | --- | ---: | ---: | --- |")
    for item in checks["sequences"]:
        lines.append(
            f"| {item['table']} | {item['event_key']} | {', '.join(item['order_by'])} | "
            f"{item['checked']} | {item['mismatched']} | {_status(item['passed'])} |"
        )
    lines.append("")

    lines.append("## 原敏感值残留检查")
    lines.append("")
    lines.append("| 命名空间 | 类型 | 原值数量 | 覆盖列 | 精确命中 | 子串命中 | 模式 | 结果 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | --- | --- |")
    for item in checks["residual"]:
        lines.append(
            f"| {item['namespace']} | {item['kind']} | {item['original_values']} | "
            f"{item['masked_columns']} | {item['exact_hits']} | {item['substring_hits']} | "
            f"{item['mode']} | {_status(item['passed'])} |"
        )
    lines.append("")

    lines.append("## 业务查询等价性")
    lines.append("")
    lines.append("| 查询 | 说明 | 源分组数 | 脱敏后分组数 | 源签名 | 脱敏签名 | 结果 |")
    lines.append("| --- | --- | ---: | ---: | --- | --- | --- |")
    for item in checks["business_queries"]:
        lines.append(
            f"| {item['id']} | {item['description']} | {item['source_groups']} | "
            f"{item['masked_groups']} | `{item['source_signature']}` | "
            f"`{item['masked_signature']}` | {_status(item['passed'])} |"
        )
    lines.append("")
    lines.append("## 输出文件")
    lines.append("")
    lines.append("| 文件 | 行数 | SHA-256 |")
    lines.append("| --- | ---: | --- |")
    for item in report["files"]:
        lines.append(f"| {item['name']} | {item.get('rows', '-')} | `{item['sha256']}` |")
    lines.append("")
    lines.append(
        "> 导出目录不包含种子、原始敏感值或内部映射表；只有通过全部校验后才会原子发布。"
    )
    lines.append("")
    return "\n".join(lines)
