from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from maskflow.settings import Settings  # noqa: E402
from maskflow.synthetic import write_source  # noqa: E402

TEST_SEED = "unit-test-seed-0123456789abcdef"


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.setenv("MASKFLOW_SEED", TEST_SEED)
    instance = Settings(
        root=ROOT,
        data_dir=tmp_path / "data",
        config_path=tmp_path / "config" / "missing.toml",
    )
    instance.ensure_dirs()
    write_source(instance.source_dir)
    return instance
