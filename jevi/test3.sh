#!/usr/bin/env bash
# test3.sh — score schema test: string state + ordered-level rating question.
# Usage: ./test3.sh [base_url]   (default: http://localhost:7001)
set -euo pipefail
BASE="${1:-http://localhost:${PORT:-7001}}"
curl -s "$BASE/v1/systemone" -H 'Content-Type: application/json' -d '{
  "state": "Help! My payouts have been failing for 3 days.",
  "model": "test",
  "questions": {"frustration": {"type": "score",
    "instructions": "How frustrated is the customer?",
    "criteria": ["Calm", "Frustrated", "Very angry"]}}
}' | tee /tmp/jevi-test3.json | jq .
jq -e '
  .answers.frustration.type == "score"
  and ((.answers.frustration.probabilities | keys_unsorted | sort) == ["0","1","2"])
  and ((.answers.frustration.legend | keys_unsorted | sort) == ["0","1","2"])
  and (.answers.frustration.score >= 0 and .answers.frustration.score <= 2)
  and ((.answers.frustration.probabilities | to_entries | map(.value) | add - 1 | fabs) < 1e-4)
' /tmp/jevi-test3.json > /dev/null && echo "TEST3 score: PASS"
