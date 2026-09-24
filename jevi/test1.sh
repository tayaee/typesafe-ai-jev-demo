#!/usr/bin/env bash
# test1.sh — choice schema test: 4096 board state + best_move choice question.
# Usage: ./test1.sh [base_url]   (default: http://localhost:7001)
set -euo pipefail
BASE="${1:-http://localhost:${PORT:-7001}}"
curl -s "$BASE/v1/systemone" -H 'Content-Type: application/json' -d '{
  "state": {"board": [[128,64,32,16],[0,0,0,8],[0,0,0,4],[0,0,0,2]], "score": 1234},
  "model": "test",
  "questions": {"best_move": {"type": "choice",
    "instructions": "Keep the largest tile in the lower-left corner. Best next slide?",
    "criteria": {"up": "Slide up. Usually bad.",
                 "down": "Slide down toward the corner. Excellent.",
                 "left": "Slide left toward the corner. Excellent.",
                 "right": "Slide right. Usually bad."}}}
}' | tee /tmp/jevi-test1.json | jq .
jq -e '
  .answers.best_move as $a
  | $a.type == "choice"
  and (["up","down","left","right"] | index($a.choice) != null)
  and (($a.probabilities | to_entries | map(.value) | add - 1 | fabs) < 1e-4)
  and ($a.confidence >= 0 and $a.confidence <= 1)
' /tmp/jevi-test1.json > /dev/null && echo "TEST1 choice: PASS"
