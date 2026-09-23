#!/usr/bin/env bash
# 전 과목 풀이 (API 키 불필요 — 로컬 Laya 모델 사용).
# 첫 실행 시 모델 가중치를 Hugging Face에서 내려받아 ~/.cache/receptron-laya 에 캐시한다.
set -euo pipefail
cd "$(dirname "$0")"

npm start -- --file csat2024_jev_full.json --subject-id korean
npm start -- --file csat2024_jev_full.json --subject-id physics1
npm start -- --file csat2024_jev_full.json --subject-id bio1
npm start -- --file csat2024_jev_full.json --subject-id japanese
