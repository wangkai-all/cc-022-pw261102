from __future__ import annotations

import csv
from pathlib import Path

from .schema import COLUMN_TYPES, TABLE_ORDER

CUSTOMERS = [
    # tenant, customer_id, name, phone, email, city, created_at
    ("T-ACME", "C1001", "张伟", "13800001001", "zhang.wei@acme.example", "北京", "2024-01-05"),
    ("T-ACME", "C1002", "李娜", "13900001002", "li.na@acme.example", "上海", "2024-02-11"),
    ("T-ACME", "C1003", "张伟", "13700001003", "zhangwei3@acme.example", "北京", "2024-03-02"),
    ("T-ACME", "C1004", "王强", None, None, "深圳", "2024-03-18"),
    ("T-ACME", "C1005", None, "13600001005", None, "广州", "2024-04-01"),
    ("T-ACME", "C1006", "陈静", "13800001001", "chen.jing@acme.example", "成都", "2024-04-22"),
    # Same raw customer_id and same phone as T-ACME, but a different tenant.
    ("T-GLOBEX", "C1001", "张伟", "13800001001", "zhang.wei@globex.example", "香港", "2024-01-09"),
    ("T-GLOBEX", "C2002", "刘洋", "13800001001", "liu.yang@globex.example", "新加坡", "2024-02-14"),
    ("T-GLOBEX", "C2003", "张伟", "13500002003", "zhangwei3@globex.example", "吉隆坡", "2024-05-06"),
    ("T-GLOBEX", "C2004", "赵敏", None, "zhao.min@globex.example", "东京", "2024-06-15"),
    ("T-INITECH", "C3001", "周杰", "13100003001", "zhou.jie@initech.example", "大阪", "2024-07-01"),
    ("T-INITECH", "C3002", "林晓", "13100003002", None, "首尔", "2024-07-19"),
]

ORDERS = [
    # tenant, order_id, customer_id, contact_phone, order_date, ship_date, amount, status
    ("T-ACME", "O10001", "C1001", "13800001001", "2024-02-01", "2024-02-03", "1280.00", "PAID"),
    ("T-ACME", "O10002", "C1001", "13800001001", "2024-03-15", "2024-03-16", "640.50", "SHIPPED"),
    ("T-ACME", "O10003", "C1001", "13800001001", "2024-05-01", None, "199.00", "PAID"),
    ("T-ACME", "O10004", "C1002", "13900001002", "2024-02-20", "2024-02-21", "450.00", "COMPLETED"),
    ("T-ACME", "O10005", "C1002", "13900001002", "2024-06-10", "2024-06-12", "89.90", "SHIPPED"),
    ("T-ACME", "O10006", "C1003", "13700001003", "2024-04-05", "2024-04-06", "320.00", "COMPLETED"),
    ("T-ACME", "O10007", "C1004", None, "2024-04-10", "2024-04-11", "55.00", "COMPLETED"),
    ("T-ACME", "O10008", "C1005", "13600001005", "2024-04-25", None, "780.00", "PAID"),
    ("T-ACME", "O10009", "C1006", "13800001001", "2024-05-12", "2024-05-13", "210.00", "SHIPPED"),
    ("T-ACME", "O10010", "C1006", None, "2024-07-01", "2024-07-02", "99.00", "COMPLETED"),
    ("T-GLOBEX", "O20001", "C1001", "13800001001", "2024-02-05", "2024-02-08", "999.00", "COMPLETED"),
    ("T-GLOBEX", "O20002", "C1001", "13800001001", "2024-06-20", None, "149.00", "PAID"),
    ("T-GLOBEX", "O20003", "C2002", "13800001001", "2024-03-03", "2024-03-04", "3200.00", "COMPLETED"),
    ("T-GLOBEX", "O20004", "C2003", "13500002003", "2024-05-20", "2024-05-21", "410.00", "SHIPPED"),
    ("T-GLOBEX", "O20005", "C2004", None, "2024-06-25", "2024-06-26", "75.00", "COMPLETED"),
    ("T-GLOBEX", "O20006", "C2004", None, "2024-07-30", None, "560.00", "PAID"),
    ("T-INITECH", "O30001", "C3001", "13100003001", "2024-07-10", "2024-07-11", "88.00", "COMPLETED"),
    ("T-INITECH", "O30002", "C3001", "13100003001", "2024-08-01", None, "120.00", "PAID"),
    # C3002 has no orders on purpose: exercises customers without child rows.
]

AFTER_SALES = [
    # tenant, case_id, order_id, customer_id, contact_email, reason, created_at, resolved_at
    ("T-ACME", "A10001", "O10002", "C1001", "zhang.wei@acme.example", "尺码不合适", "2024-03-20", "2024-03-25"),
    ("T-ACME", "A10002", "O10004", "C1002", "li.na@acme.example", "发票问题", "2024-02-25", "2024-02-27"),
    ("T-ACME", "A10003", "O10007", "C1004", None, "商品破损", "2024-04-13", "2024-04-20"),
    ("T-ACME", "A10004", "O10009", "C1006", "chen.jing@acme.example", "重复下单", "2024-05-14", None),
    ("T-GLOBEX", "A10005", "O20001", "C1001", "zhang.wei@globex.example", "物流延迟", "2024-02-12", "2024-02-18"),
    ("T-GLOBEX", "A10006", "O20003", "C2002", "liu.yang@globex.example", "退款申请", "2024-03-08", "2024-03-12"),
    ("T-GLOBEX", "A10007", "O20005", "C2004", "zhao.min@globex.example", "尺寸不符", "2024-06-28", "2024-07-02"),
    ("T-INITECH", "A10008", "O30001", "C3001", "zhou.jie@initech.example", "发票抬头", "2024-07-12", "2024-07-15"),
    ("T-INITECH", "A10009", "O30002", "C3001", None, "咨询", "2024-08-03", None),
]


def _write_csv(path: Path, table: str, rows: list[tuple]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(list(COLUMN_TYPES[table]))
        for row in rows:
            writer.writerow(["" if value is None else value for value in row])


def write_source(source_dir: Path) -> dict[str, int]:
    source_dir = Path(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "customers": CUSTOMERS,
        "orders": ORDERS,
        "after_sales": AFTER_SALES,
    }
    counts = {}
    for table in TABLE_ORDER:
        _write_csv(source_dir / f"{table}.csv", table, data[table])
        counts[table] = len(data[table])
    return counts


def ensure_source(source_dir: Path) -> dict[str, int]:
    source_dir = Path(source_dir)
    required = [source_dir / f"{table}.csv" for table in TABLE_ORDER]
    if all(path.exists() for path in required):
        return {}
    return write_source(source_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate the demo source dataset")
    parser.add_argument("--out", type=Path, default=Path("data/source"))
    args = parser.parse_args()
    counts = write_source(args.out)
    print("generated:", counts)
