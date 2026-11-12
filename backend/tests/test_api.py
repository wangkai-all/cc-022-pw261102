from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from maskflow.api import create_app
from maskflow.service import MaskingService


def make_client(settings):
    service = MaskingService(settings)
    return TestClient(create_app(settings, service)), settings


def test_api_full_flow(settings):
    client, settings = make_client(settings)

    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    payload = bootstrap.json()
    assert payload["seed"]["configured"] is True
    assert payload["dataset"]["facts"]["customers"] == 12
    rules = payload["default_rules"]

    validated = client.post("/api/rules/validate", json={"rules": rules})
    assert validated.status_code == 200
    assert validated.json()["valid"] is True

    preview = client.post("/api/preview", json={"rules": rules, "limit": 3})
    assert preview.status_code == 200
    body = preview.json()
    assert [table["name"] for table in body["tables"]] == [
        "customers",
        "orders",
        "after_sales",
    ]
    assert all(len(table["rows"]) == 3 for table in body["tables"])
    assert body["mapping"]["totals"]["values"] > 0

    before = set(settings.export_dir.glob("run-*"))
    generated = client.post("/api/generate", json={"rules": rules})
    assert generated.status_code == 200
    report = generated.json()
    assert report["published"] is True
    assert report["checks"]["passed"] is True
    assert report["totals"]["residual_hits"] == 0
    assert "seed" not in {key for key in report.keys()}

    job_id = report["job_id"]
    for name in ("customers.csv", "orders.csv", "after_sales.csv", "report.json", "report.md", "manifest.json"):
        response = client.get(f"/api/jobs/{job_id}/download/{name}")
        assert response.status_code == 200
        assert response.content
    assert not any("seed-value" in response.text for response in [client.get(f"/api/jobs/{job_id}/download/report.md")])

    job_report = client.get(f"/api/jobs/{job_id}")
    assert job_report.status_code == 200
    assert job_report.json()["job_id"] == job_id

    jobs = client.get("/api/jobs").json()
    assert any(item["job_id"] == job_id for item in jobs["jobs"])
    after = set(settings.export_dir.glob("run-*"))
    assert len(after - before) == 1


def test_api_incomplete_rules_are_rejected_without_publishing(settings):
    client, settings = make_client(settings)
    rules = deepcopy(client.get("/api/bootstrap").json()["default_rules"])
    del rules["tables"]["after_sales"]["columns"]["resolved_at"]

    response = client.post("/api/generate", json={"rules": rules})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "rules"
    assert detail["valid"] is False
    assert any("after_sales.resolved_at" in error for error in detail["errors"])
    assert not list(settings.export_dir.glob("run-*"))
    assert not list(settings.export_dir.glob(".staging-*"))


def test_api_rejects_unsafe_download_paths(settings):
    client, _ = make_client(settings)
    response = client.get("/api/jobs/run-20260101-000000-deadbeef/download/../../etc/passwd")
    assert response.status_code == 404
