from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from .checks import run_checks
from .engine import (
    MaskingEngine,
    RuleValidationError,
    SourceDataError,
    _load_source,
)
from .report import build_report, render_markdown
from .rules import Ruleset, parse_rules, validate_rules
from .schema import COLUMN_TYPES, DEFAULT_RULES, TABLE_ORDER
from .settings import SeedNotConfigured, Settings
from .synthetic import ensure_source, write_source

JOB_ID_PATTERN = re.compile(r"^run-[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")
ALLOWED_FILES = {f"{table}.csv" for table in TABLE_ORDER} | {
    "manifest.json",
    "report.json",
    "report.md",
}


class ValidationFailure(RuntimeError):
    def __init__(self, report: dict):
        self.report = report
        super().__init__("；".join(report.get("errors", [])) or "规则校验失败")


class GenerationFailed(RuntimeError):
    def __init__(self, job_id: str, checks: dict, message: str):
        self.job_id = job_id
        self.checks = checks
        super().__init__(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _count_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return max(0, sum(1 for _ in handle) - 1)


class MaskingService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.ensure_dirs()

    # ------------------------------------------------------------------ setup
    def ensure_source(self) -> dict[str, int]:
        return ensure_source(self.settings.source_dir)

    def bootstrap(self) -> dict:
        self.ensure_source()
        return {
            "seed": self.settings.seed_status(),
            "dataset": self.source_overview(),
            "default_rules": DEFAULT_RULES,
            "strategy_labels": {
                "passthrough": "保留原值",
                "surrogate_id": "代理编号",
                "fake_name": "姓名假值",
                "fake_phone": "手机号假值",
                "fake_email": "邮箱假值",
                "date_shift": "日期平移",
            },
            "jobs": self.list_jobs(),
        }

    def source_overview(self) -> dict:
        self.ensure_source()
        con = duckdb.connect()
        try:
            _load_source(con, self.settings.source_dir)
            tables = []
            total_nulls = 0
            for table in TABLE_ORDER:
                rows = con.execute(f'SELECT COUNT(*) FROM "src_{table}"').fetchone()[0]
                columns = []
                for column, dtype in COLUMN_TYPES[table].items():
                    nulls = con.execute(
                        f'SELECT COUNT(*) FROM "src_{table}" WHERE "{column}" IS NULL'
                    ).fetchone()[0]
                    total_nulls += nulls
                    columns.append({"name": column, "type": dtype, "nulls": nulls})
                tables.append({"name": table, "rows": rows, "columns": columns})

            tenants = [
                row[0]
                for row in con.execute(
                    'SELECT DISTINCT tenant_id FROM "src_customers" ORDER BY tenant_id'
                ).fetchall()
            ]
            in_all_three = con.execute(
                'SELECT COUNT(*) FROM (SELECT c.tenant_id, c.customer_id '
                'FROM "src_customers" c JOIN "src_orders" o USING (tenant_id, customer_id) '
                'JOIN "src_after_sales" a USING (tenant_id, customer_id) '
                'GROUP BY c.tenant_id, c.customer_id)'
            ).fetchone()[0]
            same_name = con.execute(
                'SELECT COUNT(*) FROM (SELECT tenant_id, name FROM "src_customers" '
                'WHERE name IS NOT NULL GROUP BY tenant_id, name '
                'HAVING COUNT(DISTINCT customer_id) > 1)'
            ).fetchone()[0]
            same_phone_tenants = con.execute(
                'SELECT COUNT(*) FROM (SELECT phone FROM "src_customers" '
                'WHERE phone IS NOT NULL GROUP BY phone HAVING COUNT(DISTINCT tenant_id) > 1)'
            ).fetchone()[0]
            same_phone_tenant = con.execute(
                'SELECT COUNT(*) FROM (SELECT tenant_id, phone FROM "src_customers" '
                'WHERE phone IS NOT NULL GROUP BY tenant_id, phone '
                'HAVING COUNT(DISTINCT customer_id) > 1)'
            ).fetchone()[0]
            missing_identity = con.execute(
                'SELECT COUNT(*) FROM "src_customers" WHERE name IS NULL '
                "OR phone IS NULL OR email IS NULL"
            ).fetchone()[0]

            facts = {
                "tenants": tenants,
                "customers": con.execute('SELECT COUNT(*) FROM "src_customers"').fetchone()[0],
                "orders": con.execute('SELECT COUNT(*) FROM "src_orders"').fetchone()[0],
                "after_sales": con.execute(
                    'SELECT COUNT(*) FROM "src_after_sales"'
                ).fetchone()[0],
                "customers_in_all_three_tables": in_all_three,
                "same_name_identity_groups": same_name,
                "same_phone_across_tenants": same_phone_tenants,
                "same_phone_within_tenant": same_phone_tenant,
                "customer_rows_with_missing_field": missing_identity,
                "null_cells": total_nulls,
            }
            return {"tables": tables, "facts": facts}
        finally:
            con.close()

    # ------------------------------------------------------------------ rules
    def validate_document(self, payload: Any) -> dict:
        rules, parse_report = parse_rules(payload)
        if rules is None:
            return parse_report.to_dict()
        self.ensure_source()
        from .engine import read_source_schema

        schema = read_source_schema(self.settings.source_dir)
        return validate_rules(rules, schema).to_dict()

    def _rules(self, payload: Any) -> Ruleset:
        rules, report = parse_rules(payload)
        if rules is None:
            raise ValidationFailure(report.to_dict())
        self.ensure_source()
        from .engine import read_source_schema

        schema = read_source_schema(self.settings.source_dir)
        semantic = validate_rules(rules, schema)
        if not semantic.valid:
            raise ValidationFailure(semantic.to_dict())
        return rules

    def _seed(self) -> tuple[str, str]:
        try:
            return self.settings.load_seed()
        except SeedNotConfigured as exc:
            raise ValidationFailure(
                {
                    "valid": False,
                    "errors": [str(exc)],
                    "warnings": [],
                    "coverage": {},
                    "rules_hash": "",
                }
            ) from exc

    # ------------------------------------------------------------------ preview
    def preview(self, payload: Any, limit: int = 5) -> dict:
        rules = self._rules(payload)
        seed, seed_source = self._seed()
        limit = max(1, min(int(limit), 50))
        engine = MaskingEngine(self.settings.source_dir, seed, rules, seed_source)
        try:
            preview = engine.preview(limit)
            preview["rule_version"] = rules.version
            preview["rules_hash"] = engine.rules_hash
            preview["seed_source"] = seed_source
            preview["valid"] = True
            return preview
        finally:
            engine.close()

    # ------------------------------------------------------------------ generate
    def generate(self, payload: Any) -> dict:
        rules = self._rules(payload)
        seed, seed_source = self._seed()
        job_id = (
            datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S")
            + "-"
            + secrets.token_hex(4)
        )
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        engine = MaskingEngine(self.settings.source_dir, seed, rules, seed_source)
        staging = self.settings.export_dir / f".staging-{job_id}"
        final = self.settings.export_dir / job_id
        try:
            engine.prepare()
            checks = run_checks(engine)
            replacements = engine.replacement_stats()
            mapping = engine.mapping_summary()
            source_rows = {
                table: engine.con.execute(
                    f'SELECT COUNT(*) FROM "src_{table}"'
                ).fetchone()[0]
                for table in TABLE_ORDER
            }
            if not checks["passed"]:
                failure = {
                    "job_id": job_id,
                    "created_at": created_at,
                    "rule_version": rules.version,
                    "rules_hash": engine.rules_hash,
                    "status": "failed",
                    "checks": checks,
                }
                _write_json(self.settings.failure_dir / f"{job_id}.json", failure)
                raise GenerationFailed(
                    job_id,
                    checks,
                    "校验未通过，未发布任何文件：" + "、".join(checks["blocking_failures"]),
                )

            staging.mkdir(parents=True, exist_ok=False)
            try:
                csv_paths = engine.export_csvs(staging)
                file_entries = []
                for table, path in zip(TABLE_ORDER, csv_paths):
                    entry = {
                        "name": path.name,
                        "rows": _count_rows(path),
                        "sha256": _sha256(path),
                    }
                    file_entries.append(entry)

                content_fingerprint = hashlib.sha256(
                    "|".join(f"{entry['name']}:{entry['sha256']}" for entry in file_entries).encode()
                ).hexdigest()[:24]

                report = build_report(
                    job_id=job_id,
                    created_at=created_at,
                    rule_version=rules.version,
                    rules_hash=engine.rules_hash,
                    seed_source=seed_source,
                    replacements=replacements,
                    mapping=mapping,
                    date_shift=checks["date_shift"],
                    checks=checks,
                    files=file_entries,
                    content_fingerprint=content_fingerprint,
                    source_rows=source_rows,
                )
                _write_json(staging / "report.json", report)
                (staging / "report.md").write_text(render_markdown(report), encoding="utf-8")

                manifest_files = list(file_entries)
                for name in ("report.json", "report.md"):
                    path = staging / name
                    manifest_files.append(
                        {"name": name, "sha256": _sha256(path), "role": "report"}
                    )
                manifest = {
                    "job_id": job_id,
                    "created_at": created_at,
                    "rule_version": rules.version,
                    "rules_hash": engine.rules_hash,
                    "content_fingerprint": content_fingerprint,
                    "seed_source": "local configuration (value not exported)",
                    "format": "csv",
                    "tables": {
                        entry["name"].removesuffix(".csv"): {
                            "file": entry["name"],
                            "rows": entry["rows"],
                            "sha256": entry["sha256"],
                        }
                        for entry in file_entries
                    },
                    "files": manifest_files,
                    "status": "published",
                }
                _write_json(staging / "manifest.json", manifest)

                os.replace(staging, final)
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                raise

            report["downloads"] = [
                {"name": "customers.csv", "url": f"/api/jobs/{job_id}/download/customers.csv"},
                {"name": "orders.csv", "url": f"/api/jobs/{job_id}/download/orders.csv"},
                {"name": "after_sales.csv", "url": f"/api/jobs/{job_id}/download/after_sales.csv"},
                {"name": "report.json", "url": f"/api/jobs/{job_id}/download/report.json"},
                {"name": "report.md", "url": f"/api/jobs/{job_id}/download/report.md"},
                {"name": "manifest.json", "url": f"/api/jobs/{job_id}/download/manifest.json"},
            ]
            report["published"] = True
            return report
        finally:
            engine.close()

    # ------------------------------------------------------------------ jobs
    def list_jobs(self) -> list[dict]:
        jobs = []
        for manifest_path in sorted(self.settings.export_dir.glob("run-*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            jobs.append(
                {
                    "job_id": manifest.get("job_id"),
                    "created_at": manifest.get("created_at"),
                    "rule_version": manifest.get("rule_version"),
                    "content_fingerprint": manifest.get("content_fingerprint"),
                    "tables": manifest.get("tables"),
                }
            )
        jobs.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return jobs

    def load_job(self, job_id: str) -> dict:
        if not JOB_ID_PATTERN.match(job_id):
            raise FileNotFoundError(job_id)
        base = self.settings.export_dir / job_id
        report_path = base / "report.json"
        manifest_path = base / "manifest.json"
        if not report_path.exists() or not manifest_path.exists():
            raise FileNotFoundError(job_id)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report["downloads"] = [
            {"name": entry["name"], "url": f"/api/jobs/{job_id}/download/{entry['name']}"}
            for entry in manifest.get("files", [])
        ]
        report["published"] = True
        return report

    def download_path(self, job_id: str, filename: str) -> Path:
        if filename not in ALLOWED_FILES:
            raise FileNotFoundError(filename)
        if not JOB_ID_PATTERN.match(job_id):
            raise FileNotFoundError(job_id)
        path = self.settings.export_dir / job_id / filename
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(filename)
        return path


def reset_demo_data(settings: Settings) -> dict[str, int]:
    """Convenience for local demos; only touches generated source files."""
    counts = write_source(settings.source_dir)
    return counts
