#!/usr/bin/env bash
# Convenience launcher (Linux/macOS): ./run.sh [play4096-laya.ts args...]
# All arguments are forwarded to src/play4096-laya.ts via tsx as-is.
#
# Examples:
#   ./run.sh --help
#   ./run.sh --dry-run --max-moves 2 --start-delay-secs 0 --new-game
#   ./run.sh --new-game --start-delay-secs 10
#   ./run.sh --connect .browser.json --shot-dir ./shots
#   ./run.sh --connect .browser.json --headless --shot-dir ./shots
#
# Needs: Node.js 20+ and npm. First run does `npm install`.
# No API key: the Laya model runs locally (weights ~1.7 GB download once,
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

exec npx tsx src/play4096-laya.ts "$@"
