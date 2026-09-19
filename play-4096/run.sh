#!/usr/bin/env bash
# Convenience launcher (Linux/macOS): ./run.sh [play4096.py args...]
# All arguments are forwarded to play4096.py as-is.
#
# Examples:
#   ./run.sh --help
#   ./run.sh --dry-run --max-moves 2 --start-delay-secs 0 --new-game
#   ./run.sh --connect existing-browser-info --url https://thereal4096.github.io \
#            --new-game --start-delay-secs 10
#   ./run.sh --connect existing-browser-info --shot-dir ./shots
#   ./run.sh --connect existing-browser-info --headless --shot-dir ./shots
#
# Needs: uv (https://docs.astral.sh/uv/getting-started/installation/)
# API key via --typesafe-api-key KEY, $TYPESAFE_API_KEY, or .env (see .env.template),
# unless --dry-run is used.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: 'uv' not found. Install it:" >&2
  echo "  https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

exec uv run play4096.py "$@"
