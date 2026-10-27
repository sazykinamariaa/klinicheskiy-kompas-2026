#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Сначала запустите ./run.sh один раз"; exit 1; }
cd backend && ../.venv/bin/python -m pytest -q "$@"
