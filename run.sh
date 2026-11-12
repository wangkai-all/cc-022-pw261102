#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "Missing .venv. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [ ! -f config/masking.local.toml ] && [ -z "${MASKFLOW_SEED:-}" ]; then
  echo "No local seed found; creating config/masking.local.toml (value is not printed)."
  .venv/bin/python scripts/setup_local.py
fi

if [ ! -f data/source/customers.csv ]; then
  .venv/bin/python scripts/generate_synthetic.py
fi

if [ ! -f frontend/dist/index.html ]; then
  echo "Missing frontend build. Run: (cd frontend && npm install && npm run build)"
  exit 1
fi

exec .venv/bin/uvicorn maskflow.api:app \
  --app-dir backend \
  --host 0.0.0.0 \
  --port "${PORT:-8000}"
