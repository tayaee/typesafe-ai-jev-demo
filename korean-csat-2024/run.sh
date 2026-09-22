#!/usr/bin/env bash
set -euo pipefail

if [ -z "${TYPESAFE_API_KEY:-}" ]; then
  echo "ERROR: TYPESAFE_API_KEY is not set." >&2
  echo "  export TYPESAFE_API_KEY=..." >&2
  exit 1
fi

uv run csat.py --file csat2024_jev_full.json --subject-id korean --typesafe-api-key $TYPESAFE_API_KEY
uv run csat.py --file csat2024_jev_full.json --subject-id physics1  --typesafe-api-key $TYPESAFE_API_KEY
uv run csat.py --file csat2024_jev_full.json --subject-id bio1 --typesafe-api-key $TYPESAFE_API_KEY
uv run csat.py --file csat2024_jev_full.json --subject-id japanese --typesafe-api-key $TYPESAFE_API_KEY
