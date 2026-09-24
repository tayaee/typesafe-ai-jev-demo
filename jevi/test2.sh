#!/usr/bin/env bash
# test2.sh — noul schema test: string state + urgency yes/no question.
# Usage: ./test2.sh [base_url]   (default: http://localhost:7001)
set -euo pipefail
BASE="${1:-http://localhost:${PORT:-7001}}"
curl -s "$BASE/v1/systemone" -H 'Content-Type: application/json' -d '{
  "state": "Stripe account connection has been failing for 3 days. Losing sales. Help ASAP.",
  "model": "test",
  "questions": {"urgency": {"type": "noul",
    "instructions": "Does this message express urgency?"}}
}' | tee /tmp/jevi-test2.json | jq .
jq -e '
  .answers.urgency.type == "noul"
  and (.answers.urgency.noul >= 0 and .answers.urgency.noul <= 1)
' /tmp/jevi-test2.json > /dev/null && echo "TEST2 noul: PASS"
