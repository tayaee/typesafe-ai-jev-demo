#!/usr/bin/env bash
# jevi launcher (Linux/macOS): uv run web.py <args>
#   ./web.sh list-models
#   ./web.sh run [--model Qwen/Qwen3.5-2B] [--host 0.0.0.0] [--port 7001] [--hf-token $HF_TOKEN]
set -euo pipefail
cd "$(dirname "$0")"
exec uv run web.py "$@"
