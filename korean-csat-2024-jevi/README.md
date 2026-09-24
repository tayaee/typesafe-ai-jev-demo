# korean-csat-2024-jevi

CSAT(수능) 문제를 로컬 [jevi](../jevi/) 서버(SystemOne 호환, 기본
`http://localhost:7001`)에게 그대로 출제하고 채점하는 프로그램.
`../korean-csat-2024-jev/`의 jevi 포트 — API 키 불필요.

Sibling: [`../korean-csat-2024-jev/`](../korean-csat-2024-jev/) — 같은 문제를
TypeSafe SystemOne (`jev-latest`) HTTP API로 푼다. 출제 형식(state 텍스트,
choice 질문 1개)과 채점/출력 스키마를 동일하게 유지(`jev_*` 필드명 그대로)해
두 백엔드의 결과를 비교할 수 있고, `analyze-confidence.py` /
`analyze-confidence.sh`를 그대로 수행할 수 있다.

## 실행

먼저 jevi 서버를 띄운다:

```bash
cd ../jevi
./web.sh run   # 기본 모델, 포트 7001
```

그 다음:

```bash
cd ../korean-csat-2024-jevi
./run.sh --file csat2024_jev_full.json --subject-id korean --limit 3
./csat-all.sh   # 전 과목 (korean, physics1, bio1, japanese) 풀이
```

URL 변경: `JEVI_URL=http://host:port/v1/systemone ./run.sh ...`
(또는 `--api-url` 옵션).

## 결과 요약

* 미실행 (실행 후 여기에 과목별 점수를 기록한다)
