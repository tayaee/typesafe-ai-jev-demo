#!/usr/bin/env bash
# 전 과목 풀이 (API 키 불필요 — 로컬 jevi 서버 사용, 기본 http://localhost:7001).
# 먼저 ../jevi 에서 서버 실행: ./web.sh run  (또는 ./web.sh run --model test)
# URL 변경: JEVI_URL=http://host:port/v1/systemone ./csat-all.sh
set -euo pipefail
cd "$(dirname "$0")"

: "${JEVI_URL:=http://localhost:7001/v1/systemone}"

./run.sh --file csat2024_jev_full.json --subject-id korean --api-url "$JEVI_URL"
./run.sh --file csat2024_jev_full.json --subject-id physics1 --api-url "$JEVI_URL"
./run.sh --file csat2024_jev_full.json --subject-id bio1 --api-url "$JEVI_URL"
./run.sh --file csat2024_jev_full.json --subject-id japanese --api-url "$JEVI_URL"
