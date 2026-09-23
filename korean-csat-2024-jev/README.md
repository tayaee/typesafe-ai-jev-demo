# korean-csat-2024-jev

CSAT(수능) 문제를 Jev(System One)에게 그대로 출제하고 채점하는 프로그램.

Sibling: [`../korean-csat-2024-laya/`](../korean-csat-2024-laya/) — 같은 문제를 로컬
[Laya](https://github.com/receptron/laya) (open-source Jev-compatible System-1 모델,
ONNX Runtime, API 키 불필요)로 푼다. 출제 형식과 채점/출력 스키마를 동일하게
유지해 두 백엔드의 결과를 비교할 수 있다.

## 실행

```bash
export TYPESAFE_API_KEY=...
./run.sh
```

## 결과 요약 (jev-1.13.0)

* 국어: 76/100점 (76.0%, 45문항, 제외 0)
* 물리학Ⅰ: 12/47점 (25.5%, 19문항, 3점 1문항 제외)
* 생명과학Ⅰ: 24/50점 (48.0%, 20문항, 제외 0)
* 일본어Ⅰ: 41/49점 (83.7%, 29문항, 1점 1문항 제외)
