from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PACKAGE_ROOT / "data"
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "masking.local.toml"
SEED_ENV_VAR = "MASKFLOW_SEED"
MIN_SEED_LENGTH = 8


class SeedNotConfigured(RuntimeError):
    """Raised when no local seed is available for deterministic masking."""


@dataclass
class Settings:
    root: Path
    data_dir: Path
    config_path: Path

    @property
    def source_dir(self) -> Path:
        return self.data_dir / "source"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def failure_dir(self) -> Path:
        return self.data_dir / "failures"

    @classmethod
    def default(cls) -> "Settings":
        data_dir = Path(os.environ.get("MASKFLOW_DATA_DIR", DEFAULT_DATA_DIR))
        config_path = Path(os.environ.get("MASKFLOW_CONFIG", DEFAULT_CONFIG_PATH))
        return cls(root=PACKAGE_ROOT, data_dir=data_dir.resolve(), config_path=config_path.resolve())

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.failure_dir.mkdir(parents=True, exist_ok=True)

    def load_seed(self) -> tuple[str, str]:
        """Return (seed, human readable source). Never include the seed in responses."""
        env_seed = os.environ.get(SEED_ENV_VAR)
        if env_seed is not None:
            seed = env_seed.strip()
            if len(seed) < MIN_SEED_LENGTH:
                raise SeedNotConfigured(
                    f"{SEED_ENV_VAR} is too short; use at least {MIN_SEED_LENGTH} characters."
                )
            return seed, f"environment variable {SEED_ENV_VAR}"

        if self.config_path.exists():
            try:
                with self.config_path.open("rb") as handle:
                    config = tomllib.load(handle)
                seed = str(config.get("masking", {}).get("seed", "")).strip()
            except (OSError, tomllib.TOMLDecodeError) as exc:
                raise SeedNotConfigured(f"Could not read local config: {exc}") from exc
            if len(seed) < MIN_SEED_LENGTH:
                raise SeedNotConfigured(
                    f"Local config {self.config_path.name} does not contain a valid "
                    f"[masking].seed (>= {MIN_SEED_LENGTH} characters)."
                )
            return seed, f"local config ({self.config_path.name})"

        raise SeedNotConfigured(
            "No masking seed configured. Run `python scripts/setup_local.py` to create "
            f"{self.config_path}, or set {SEED_ENV_VAR} locally."
        )

    def seed_status(self) -> dict:
        try:
            self.load_seed()
            return {
                "configured": True,
                "detail": "本地配置已加载，种子值不会写入导出文件",
            }
        except SeedNotConfigured as exc:
            return {"configured": False, "detail": str(exc)}
