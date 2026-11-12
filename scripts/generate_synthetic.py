#!/usr/bin/env python3
"""Write the synthetic three-table demo dataset."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from maskflow.synthetic import write_source  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "source")
    args = parser.parse_args()
    print(write_source(args.out))


if __name__ == "__main__":
    main()
