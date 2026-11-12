#!/usr/bin/env python3
"""Create the local-only masking seed and the demo source dataset."""
from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from maskflow.synthetic import write_source  # noqa: E402

DEFAULT_CONFIG = ROOT / "config" / "masking.local.toml"
DEFAULT_SOURCE = ROOT / "data" / "source"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="overwrite an existing local seed")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()

    if args.config.exists() and not args.force:
        print(f"seed already exists: {args.config} (not overwritten)")
    else:
        seed = secrets.token_urlsafe(48)
        args.config.parent.mkdir(parents=True, exist_ok=True)
        args.config.write_text(
            "[masking]\n"
            "# Local-only seed for deterministic masking.\n"
            "# Never commit this file and never include it in an export.\n"
            f'seed = "{seed}"\n',
            encoding="utf-8",
        )
        os.chmod(args.config, stat.S_IRUSR | stat.S_IWUSR)
        print(f"wrote local seed config: {args.config} (value not printed)")

    counts = write_source(args.source)
    print(f"demo source rows: {counts}")


if __name__ == "__main__":
    main()
