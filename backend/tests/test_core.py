from __future__ import annotations

import csv
from collections import defaultdict
from copy import deepcopy

import pytest

from maskflow.checks import run_checks
from maskflow.engine import MaskingEngine
from maskflow.mapping import AllocationError, _candidate, allocate_namespace
from maskflow.rules import NamespaceSpec, load_default_rules
from maskflow.service import GenerationFailed, MaskingService, ValidationFailure
from maskflow.synthetic import AFTER_SALES, CUSTOMERS, ORDERS


def make_engine(settings, seed: str = "unit-test-seed-0123456789abcdef", rules=None):
    engine = MaskingEngine(
        settings.source_dir,
        seed,
        rules or load_default_rules(),
        "test environment variable",
    )
    engine.prepare()
    return engine


def customer_rows(engine):
    joins, condition = engine.pk_join("customers", "s", "o")
    return engine.con.execute(
        "SELECT s.tenant_id, s.customer_id, s.name, s.phone, s.email, "
        "o.customer_id, o.name, o.phone, o.email "
        f'FROM "src_customers" s {" ".join(joins)} '
        f'JOIN "out_customers" o ON {condition}'
    ).fetchall()


def test_cross_table_consistency_tenant_isolation_and_names(settings):
    engine = make_engine(settings)
    try:
        rows = customer_rows(engine)
        assert len(rows) == len(CUSTOMERS)

        by_raw_id = defaultdict(set)
        by_name = defaultdict(set)
        by_phone = defaultdict(set)
        nulls = []
        for tenant, raw_id, name, phone, email, masked_id, masked_name, masked_phone, masked_email in rows:
            by_raw_id[raw_id].add((tenant, masked_id))
            if name is not None:
                by_name[(tenant, name)].add(masked_name)
            if phone is not None:
                by_phone[(tenant, phone)].add(masked_phone)
            if phone is None:
                nulls.append(masked_phone)
            if name is None:
                nulls.append(masked_name)
            if email is None:
                nulls.append(masked_email)

        # Same raw customer id in two tenants must map differently.
        acme_c1001 = dict(by_raw_id["C1001"])["T-ACME"]
        globex_c1001 = dict(by_raw_id["C1001"])["T-GLOBEX"]
        assert acme_c1001 != globex_c1001

        # Same name, different identity must never be merged.
        for (tenant, name), masked_names in by_name.items():
            if name == "张伟":
                assert len(masked_names) == 2, (tenant, masked_names)
                assert len(set(masked_names)) == 2

        # Same phone inside a tenant and across tenants gets distinct fakes.
        for (tenant, phone), masked_phones in by_phone.items():
            if phone == "13800001001":
                assert len(masked_phones) == 2, (tenant, masked_phones)
                assert len(set(masked_phones)) == 2
        all_masked_138 = {
            masked
            for (tenant, phone), masked_set in by_phone.items()
            if phone == "13800001001"
            for masked in masked_set
        }
        assert len(all_masked_138) == 4

        # NULL phone/email/name stay NULL.
        assert all(value is None for value in nulls)
        assert engine.con.execute(
            'SELECT COUNT(*) FROM "out_customers" WHERE phone IS NULL'
        ).fetchone()[0] == 2

        # Customer id is identical in all three child tables.
        assert engine.con.execute(
            'SELECT COUNT(*) FROM "out_orders" o JOIN "out_customers" c '
            "USING (tenant_id, customer_id) WHERE o.customer_id <> c.customer_id"
        ).fetchone()[0] == 0
        assert engine.con.execute(
            'SELECT COUNT(*) FROM "out_after_sales" a JOIN "out_customers" c '
            "USING (tenant_id, customer_id) WHERE a.customer_id <> c.customer_id"
        ).fetchone()[0] == 0

        # Contact phone/email copied from the customer row must use the same fake.
        assert engine.con.execute(
            'SELECT COUNT(*) FROM "src_orders" so '
            'JOIN "src_customers" sc USING (tenant_id, customer_id) '
            'JOIN "out_orders" oo USING (tenant_id, order_id) '
            'JOIN "out_customers" oc USING (tenant_id, customer_id) '
            "WHERE so.contact_phone IS NOT NULL AND sc.phone IS NOT NULL "
            "AND so.contact_phone = sc.phone AND oo.contact_phone <> oc.phone"
        ).fetchone()[0] == 0
        assert engine.con.execute(
            'SELECT COUNT(*) FROM "src_after_sales" sa '
            'JOIN "src_customers" sc USING (tenant_id, customer_id) '
            'JOIN "out_after_sales" oa USING (tenant_id, case_id) '
            'JOIN "out_customers" oc USING (tenant_id, customer_id) '
            "WHERE sa.contact_email IS NOT NULL AND sc.email IS NOT NULL "
            "AND sa.contact_email = sc.email AND oa.contact_email <> oc.email"
        ).fetchone()[0] == 0
    finally:
        engine.close()


def test_all_checks_pass(settings):
    engine = make_engine(settings)
    try:
        checks = run_checks(engine)
        assert checks["passed"], checks["blocking_failures"]
        assert all(item["passed"] for item in checks["primary_keys"])
        assert all(item["passed"] for item in checks["foreign_keys"])
        assert all(item["passed"] for item in checks["residual"])
        assert all(item["passed"] for item in checks["business_queries"])
    finally:
        engine.close()


def test_date_shift_is_per_customer_and_preserves_intervals(settings):
    engine = make_engine(settings)
    try:
        date_columns = {
            "customers": ["created_at"],
            "orders": ["order_date", "ship_date"],
            "after_sales": ["created_at", "resolved_at"],
        }
        offsets = defaultdict(set)
        for table, columns in date_columns.items():
            joins, condition = engine.pk_join(table, "s", "o")
            for column in columns:
                for tenant, customer, difference in engine.con.execute(
                    f'SELECT s.tenant_id, s.customer_id, date_diff(\'day\', s."{column}", o."{column}") '
                    f'FROM "src_{table}" s {" ".join(joins)} '
                    f'JOIN "out_{table}" o ON {condition} '
                    f'WHERE s."{column}" IS NOT NULL'
                ).fetchall():
                    offsets[(tenant, customer)].add(difference)

        assert offsets
        for key, values in offsets.items():
            assert len(values) == 1, (key, values)
            value = next(iter(values))
            assert settings is not None
            assert -30 <= value <= 30

        checks = run_checks(engine)
        assert checks["date_shift"]["passed"]
        assert checks["date_shift_columns"] and all(
            item["passed"] for item in checks["date_shift_columns"]
        )
        assert all(item["passed"] for item in checks["intervals"])
        assert all(item["passed"] for item in checks["sequences"])
    finally:
        engine.close()


def test_determinism_same_seed_and_different_seed(settings, tmp_path):
    rules = load_default_rules()

    def export(seed: str, target: str, rule_set=None):
        directory = tmp_path / target
        directory.mkdir()
        engine = make_engine(settings, seed=seed, rules=rule_set)
        try:
            engine.export_csvs(directory)
        finally:
            engine.close()
        return {
            path.name: path.read_bytes() for path in sorted(directory.glob("*.csv"))
        }

    first = export("seed-alpha-0123456789", "first")
    second = export("seed-alpha-0123456789", "second")
    assert first == second

    other_seed = export("seed-beta-9876543210", "other")
    assert first["customers.csv"] != other_seed["customers.csv"]
    assert first["orders.csv"] != other_seed["orders.csv"]

    other_rules = rules.model_copy(deep=True)
    other_rules.version = "1.0.1"
    other_version = export("seed-alpha-0123456789", "other-version", other_rules)
    assert first["customers.csv"] != other_version["customers.csv"]


def test_target_length_limits(settings):
    payload = load_default_rules().model_dump(exclude_none=True)
    surrogate_columns = [
        ("customers", "customer_id"),
        ("orders", "customer_id"),
        ("after_sales", "customer_id"),
    ]
    phone_columns = [("customers", "phone"), ("orders", "contact_phone")]
    email_columns = [("customers", "email"), ("after_sales", "contact_email")]
    for table, column in surrogate_columns:
        payload["tables"][table]["columns"][column]["max_length"] = 7
    for table, column in phone_columns:
        payload["tables"][table]["columns"][column]["max_length"] = 9
        payload["tables"][table]["columns"][column]["prefixes"] = ["170"]
    for table, column in email_columns:
        payload["tables"][table]["columns"][column]["max_length"] = 22
        payload["tables"][table]["columns"][column]["domain"] = "m.example"
    payload["tables"]["customers"]["columns"]["name"]["max_length"] = 2

    from maskflow.rules import Ruleset, rules_hash, validate_rules
    from maskflow.engine import read_source_schema

    rules = Ruleset.model_validate(payload)
    report = validate_rules(rules, read_source_schema(settings.source_dir))
    assert report.valid, report.errors
    engine = make_engine(settings, rules=rules)
    try:
        assert engine.con.execute(
            'SELECT MAX(length(customer_id)) FROM "out_customers"'
        ).fetchone()[0] <= 7
        assert engine.con.execute(
            'SELECT MAX(length(phone)) FROM "out_customers" WHERE phone IS NOT NULL'
        ).fetchone()[0] == 9
        assert engine.con.execute(
            'SELECT MAX(length(email)) FROM "out_customers" WHERE email IS NOT NULL'
        ).fetchone()[0] <= 22
        assert engine.con.execute(
            'SELECT MAX(length(name)) FROM "out_customers" WHERE name IS NOT NULL'
        ).fetchone()[0] <= 2
        assert engine.con.execute(
            "SELECT COUNT(*) FROM \"out_customers\" WHERE phone IS NOT NULL "
            "AND NOT starts_with(phone, '170')"
        ).fetchone()[0] == 0
    finally:
        engine.close()


def test_collision_resolution_and_exhaustion():
    spec = NamespaceSpec(namespace="tiny", kind="surrogate_id", max_length=1, prefix="")
    keys = [("T", "", f"C{index:03d}") for index in range(20)]
    rows, stats = allocate_namespace(spec, keys, [], "seed", "1.0.0", "hash")
    assert len(rows) == 20
    assert len({row.fake_value for row in rows}) == 20 == stats.values

    # A banned original forces deterministic re-roll instead of leaking a source value.
    target = ("T", "", "C000")
    first_candidate = _candidate(spec, "seed", "1.0.0", "hash", *target, 0)
    rows, stats = allocate_namespace(
        spec, [target], [first_candidate], "seed", "1.0.0", "hash"
    )
    assert rows[0].fake_value != first_candidate
    assert stats.residual_avoided >= 1

    with pytest.raises(AllocationError):
        allocate_namespace(
            spec,
            [("T", "", f"X{index:03d}") for index in range(40)],
            [],
            "seed",
            "1.0.0",
            "hash",
            max_attempts=100,
        )


def test_incomplete_rules_block_publication(settings):
    service = MaskingService(settings)
    payload = load_default_rules().model_dump(exclude_none=True)
    del payload["tables"]["customers"]["columns"]["phone"]

    report = service.validate_document(payload)
    assert report["valid"] is False
    assert any("customers.phone" in error for error in report["errors"])

    with pytest.raises(ValidationFailure):
        service.generate(payload)
    assert not list(settings.export_dir.glob("run-*"))

    # FK strategy/namespace drift must also fail before any files are written.
    drift = load_default_rules().model_dump(exclude_none=True)
    drift["tables"]["orders"]["columns"]["customer_id"]["namespace"] = "other_customer"
    with pytest.raises(ValidationFailure):
        service.generate(drift)
    assert not list(settings.export_dir.glob("run-*"))


def test_seed_missing_blocks_preview_and_generation(settings, monkeypatch):
    monkeypatch.delenv("MASKFLOW_SEED")
    service = MaskingService(settings)
    payload = load_default_rules().model_dump(exclude_none=True)
    with pytest.raises(ValidationFailure) as preview_error:
        service.preview(payload)
    assert "seed" in str(preview_error.value).lower() or "种子" in str(preview_error.value)
    with pytest.raises(ValidationFailure):
        service.generate(payload)
    assert not list(settings.export_dir.glob("run-*"))


def test_broken_foreign_key_never_publishes_half_a_dataset(settings):
    # Inject an orphan after-sales row that references missing parent rows.
    path = settings.source_dir / "after_sales.csv"
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ["T-ACME", "A99999", "O99999", "C9999", "orphan@example.com", "孤儿记录", "2024-08-01", "2024-08-02"]
        )

    service = MaskingService(settings)
    payload = load_default_rules().model_dump(exclude_none=True)
    with pytest.raises(GenerationFailed) as error:
        service.generate(payload)
    assert error.value.checks["passed"] is False
    assert "foreign_keys" in error.value.checks["blocking_failures"]
    assert not list(settings.export_dir.glob("run-*"))
    assert not list(settings.export_dir.glob(".staging-*"))
    assert list(settings.failure_dir.glob("*.json"))


def test_export_has_no_seed_and_no_original_sensitive_values(settings):
    service = MaskingService(settings)
    payload = load_default_rules().model_dump(exclude_none=True)
    report = service.generate(payload)
    job_dir = settings.export_dir / report["job_id"]
    files = list(job_dir.glob("*"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)

    seed, _ = settings.load_seed()
    assert seed not in text

    originals = set()
    for _, customer_id, name, phone, email, *_ in CUSTOMERS:
        originals.update(value for value in (customer_id, name, phone, email) if value)
    for row in ORDERS:
        originals.update(value for value in (row[2], row[3]) if value)
    for row in AFTER_SALES:
        originals.update(value for value in (row[3], row[4]) if value)
    for value in originals:
        assert value not in text, f"original sensitive value leaked: {value}"

    assert report["totals"]["residual_hits"] == 0
    assert report["checks"]["passed"] is True
    assert report["published"] is True
    assert (job_dir / "manifest.json").exists()
    assert not list(settings.export_dir.glob(".staging-*"))
