#!/usr/bin/env bash
# Convenience launcher (Linux/macOS): ./run.sh --file csat2024_jev_full.json --subject-id korean [...]
# All arguments are forwarded to csat.py as-is.
#
# Examples:
#   ./run.sh --help
#   ./run.sh --file csat2024_jev_full.json --subject-id korean --limit 3
#   ./run.sh --file csat2024_jev_full.json --subject-id korean
#
# Needs: Python 3.10+ and uv. No API key: talks to the local jevi server
# (../jevi/web.sh run, default http://localhost:7001). Override with:
#   JEVI_URL=http://host:port/v1/systemone ./run.sh ...
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: 'uv' not found. Install uv (https://docs.astral.sh/uv/)." >&2
  exit 1
fi

exec uv run csat.py "$@"
