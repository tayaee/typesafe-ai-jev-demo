# korean-csat-2024-laya — 로컬 Laya로 푸는 수능 2024

CSAT(수능) 문제를 로컬 [Laya](https://github.com/receptron/laya) System-1
결정 모델(open-source, Jev-compatible, ONNX Runtime)에게 그대로 출제하고
채점하는 프로그램. API 키 불필요 — 첫 실행에 가중치를 한 번 내려받은 뒤에는
네트워크 없이 동작한다.

Sibling: [`../korean-csat-2024-jev/`](../korean-csat-2024-jev/) — 같은 문제를
TypeSafe SystemOne (`jev-latest`) HTTP API로 푼다. 출제 형식(state 텍스트,
choice 질문 1개)과 채점/출력 스키마를 동일하게 유지해 두 백엔드의 결과를
비교할 수 있다.

## Setup

Needs: Node.js 20+ and `npm`.

```bash
cd korean-csat-2024-laya
npm install
```

첫 실행 시 ONNX 가중치를 Hugging Face(`receptron/laya-onnx`)에서 내려받아
`~/.cache/receptron-laya`에 캐시한다 (`LAYA_CACHE`로 변경 가능, 또는
`--model-dir`로 `export/export_onnx.py`의 로컬 산출물을 지정).
`../play-4096-laya`와 동일한 기본값(repo root의 English 체크포인트)을 사용한다.
`--dry-run`은 모델 없이 배선만 테스트한다
(다운로드 없음).

## Usage

```bash
npm start -- --help
npm start -- --file csat2024_jev_full.json --subject-id korean --limit 3 --dry-run
npm start -- --file csat2024_jev_full.json --subject-id korean
./csat-all.sh   # 전 과목 (korean, physics1, bio1, japanese) 풀이
```

`./run.sh` / `run.bat`은 첫 실행에 `npm install`을 하고 모든 인자를
`src/csat-laya.ts`에 그대로 넘기는 thin wrapper다.

`csat2024_jev_full.json`은 jev 폴더와 동일한 시험 문제 데이터셋이다.
결과 JSON 스키마도 jev 버전과 동일하다 (`jev_*` 필드가 `laya_*`로 바뀐 것만
제외). 따라서 `analyze-confidence.py` / `analyze-confidence.sh`로 신뢰도
기반 선택적 분류 분석을 그대로 수행할 수 있다 (laya 폴더의 복사본은
`laya_answer`를 읽도록 패치되어 있고 `jev_*` 결과 파일도 함께 분석 가능하다).

## 결과 요약

* 미실행 (실행 후 여기에 과목별 점수를 기록한다)
