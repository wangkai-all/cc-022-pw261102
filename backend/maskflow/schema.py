from __future__ import annotations

from typing import Any

# Explicit source schema keeps DuckDB type inference stable, even for all-NULL columns.
COLUMN_TYPES: dict[str, dict[str, str]] = {
    "customers": {
        "tenant_id": "VARCHAR",
        "customer_id": "VARCHAR",
        "name": "VARCHAR",
        "phone": "VARCHAR",
        "email": "VARCHAR",
        "city": "VARCHAR",
        "created_at": "DATE",
    },
    "orders": {
        "tenant_id": "VARCHAR",
        "order_id": "VARCHAR",
        "customer_id": "VARCHAR",
        "contact_phone": "VARCHAR",
        "order_date": "DATE",
        "ship_date": "DATE",
        "amount": "DECIMAL(12, 2)",
        "status": "VARCHAR",
    },
    "after_sales": {
        "tenant_id": "VARCHAR",
        "case_id": "VARCHAR",
        "order_id": "VARCHAR",
        "customer_id": "VARCHAR",
        "contact_email": "VARCHAR",
        "reason": "VARCHAR",
        "created_at": "DATE",
        "resolved_at": "DATE",
    },
}

TABLE_ORDER = ["customers", "orders", "after_sales"]

PHONE_PREFIXES = ["170", "171", "172", "173"]

DEFAULT_RULES: dict[str, Any] = {
    "version": "1.0.0",
    "tenant_column": "tenant_id",
    "date_shift": {"min_days": -30, "max_days": 30},
    "tables": {
        "customers": {
            "primary_key": ["tenant_id", "customer_id"],
            "foreign_keys": [],
            "columns": {
                "tenant_id": {"strategy": "passthrough"},
                "customer_id": {
                    "strategy": "surrogate_id",
                    "namespace": "customer",
                    "prefix": "MC",
                    "max_length": 12,
                },
                "name": {
                    "strategy": "fake_name",
                    "namespace": "person_name",
                    "identity": "customer_id",
                    "max_length": 8,
                },
                "phone": {
                    "strategy": "fake_phone",
                    "namespace": "phone",
                    "identity": "customer_id",
                    "max_length": 11,
                    "prefixes": PHONE_PREFIXES,
                },
                "email": {
                    "strategy": "fake_email",
                    "namespace": "email",
                    "identity": "customer_id",
                    "max_length": 40,
                    "domain": "masked.example",
                },
                "city": {"strategy": "passthrough"},
                "created_at": {"strategy": "date_shift", "identity": "customer_id"},
            },
        },
        "orders": {
            "primary_key": ["tenant_id", "order_id"],
            "foreign_keys": [
                {
                    "columns": ["tenant_id", "customer_id"],
                    "references": {
                        "table": "customers",
                        "columns": ["tenant_id", "customer_id"],
                    },
                }
            ],
            "columns": {
                "tenant_id": {"strategy": "passthrough"},
                "order_id": {"strategy": "passthrough"},
                "customer_id": {
                    "strategy": "surrogate_id",
                    "namespace": "customer",
                    "prefix": "MC",
                    "max_length": 12,
                },
                "contact_phone": {
                    "strategy": "fake_phone",
                    "namespace": "phone",
                    "identity": "customer_id",
                    "max_length": 11,
                    "prefixes": PHONE_PREFIXES,
                },
                "order_date": {"strategy": "date_shift", "identity": "customer_id"},
                "ship_date": {"strategy": "date_shift", "identity": "customer_id"},
                "amount": {"strategy": "passthrough"},
                "status": {"strategy": "passthrough"},
            },
        },
        "after_sales": {
            "primary_key": ["tenant_id", "case_id"],
            "foreign_keys": [
                {
                    "columns": ["tenant_id", "order_id"],
                    "references": {"table": "orders", "columns": ["tenant_id", "order_id"]},
                },
                {
                    "columns": ["tenant_id", "customer_id"],
                    "references": {
                        "table": "customers",
                        "columns": ["tenant_id", "customer_id"],
                    },
                },
            ],
            "columns": {
                "tenant_id": {"strategy": "passthrough"},
                "case_id": {"strategy": "passthrough"},
                "order_id": {"strategy": "passthrough"},
                "customer_id": {
                    "strategy": "surrogate_id",
                    "namespace": "customer",
                    "prefix": "MC",
                    "max_length": 12,
                },
                "contact_email": {
                    "strategy": "fake_email",
                    "namespace": "email",
                    "identity": "customer_id",
                    "max_length": 40,
                    "domain": "masked.example",
                },
                "reason": {"strategy": "passthrough"},
                "created_at": {"strategy": "date_shift", "identity": "customer_id"},
                "resolved_at": {"strategy": "date_shift", "identity": "customer_id"},
            },
        },
    },
    "invariants": [
        {
            "table": "orders",
            "left": "order_date",
            "right": "ship_date",
            "description": "下单日期不晚于发货日期",
        },
        {
            "table": "after_sales",
            "left": "created_at",
            "right": "resolved_at",
            "description": "售后受理时间不晚于解决时间",
        },
    ],
}

STRATEGY_LABELS = {
    "passthrough": "保留原值",
    "surrogate_id": "代理编号",
    "fake_name": "姓名假值",
    "fake_phone": "手机号假值",
    "fake_email": "邮箱假值",
    "date_shift": "日期平移",
}
