#!/usr/bin/env bash
# Convenience launcher (Linux/macOS): ./run.sh [csat-laya.ts args...]
# All arguments are forwarded to src/csat-laya.ts via tsx as-is.
#
# Examples:
#   ./run.sh --help
#   ./run.sh --file csat2024_jev_full.json --subject-id korean --limit 3 --dry-run
#   ./run.sh --file csat2024_jev_full.json --subject-id korean
#
# Needs: Node.js 20+ and npm. First run does `npm install`.
# No API key: the Laya model runs locally (weights download once,
# cached under ~/.cache/receptron-laya), unless --dry-run is used.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: 'node' not found. Install Node.js 20+." >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: 'npm' not found. Install npm." >&2
  exit 1
fi

if [ ! -d node_modules ]; then
  echo "[run.sh] first run: npm install ..."
  npm install
fi

exec npx tsx src/csat-laya.ts "$@"
