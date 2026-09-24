# jevi 모델별 응답시간 (best of 5)

- 측정일: 2026-09-24 (KST 아님, 서버 로컬 EDT 기준 03:43–05:03)
- 머신: GB10 (CUDA), machine-id `7af66f30…`
- 방법: 모델마다 `./web.sh run --model <id> --port 7001` 기동 → `/health` 대기 →
  `time ./test1.sh`, `time ./test2.sh`, `time ./test3.sh`를 각 5회 반복 →
  PASS한 실행 중 최단값(ms)을 기록. jevi는 모델 출력이 JSON이 아니면
  heuristic fallback으로 답하므로, 시간 = (모델 생성 최대 256토큰) + 폴백이다.
- 정렬: 합계(test1+test2+test3) 오름차순.

| # | 모델 | test1(choice) | test2(noul) | test3(score) | 합계 |
|---|------|---:|---:|---:|---:|
| 1 | test (offline heuristic, 가중치 없음) | 10 | 9 | 10 | 29 |
| 2 | OpenGVLab/InternVL3_5-1B-HF | 628 | 113 | 636 | 1377 |
| 3 | HuggingFaceTB/SmolVLM2-500M-Video-Instruct | 844 | 216 | 604 | 1664 |
| 4 | OpenGVLab/InternVL3_5-2B-HF | 674 | 207 | 862 | 1743 |
| 5 | Qwen/Qwen3-VL-2B-Instruct | 721 | 194 | 920 | 1835 |
| 6 | nvidia/Cosmos-Reason2-2B | 1111 | 283 | 1060 | 2454 |
| 7 | Qwen/Qwen2.5-0.5B-Instruct | 2234 | 110 | 1253 | 3597 |
| 8 | Qwen/Qwen2.5-VL-3B-Instruct | 2501 | 315 | 1321 | 4137 |
| 9 | Qwen/Qwen3-0.6B | 3076 | 3022 | 3034 | 9132 |
| 10 | nvidia/Cosmos-Reason2-8B | 5127 | 1068 | 3612 | 9807 |
| 11 | HuggingFaceTB/SmolLM2-1.7B-Instruct | 38 | 5485 | 5515 | 11038 |
| 12 | Qwen/Qwen3-1.7B | 6269 | 6248 | 6264 | 18781 |
| 13 | HuggingFaceTB/SmolLM3-3B | 9184 | 1500 | 9167 | 19851 |
| 14 | Qwen/Qwen3.5-2B | 6836 | 6847 | 6864 | 20547 |
| 15 | nvidia/Llama-3.1-Nemotron-Nano-4B-v1.1 | 12216 | 6266 | 12260 | 30742 |
| 16 | nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16 | 12513 | 12508 | 12563 | 37584 |
| — | openbmb/MiniCPM-V-4_5 | 측정 불가 | 측정 불가 | 측정 불가 | — |

## 측정 불가

- `openbmb/MiniCPM-V-4_5`: jevi의 `pipeline("image-text-to-text")` 경로와
  호환 안 됨. 커스텀 `MiniCPMVConfig`가 transformers의
  `AutoModelForImageTextToText`에서 인식되지 않음
  (`MiniCPMV4_6Config`까지만 지원). 전용 `model.chat()` 코드가 필요해서 제외.
  (참고: llama.cpp/GGUF로는 CPU 추론이 공식 지원됨)

## 비고

- test2(noul)가 유독 빠른 모델(Qwen2.5-0.5B 110ms, InternVL 113–207ms 등)은
  짧은 프롬프트에 유효 JSON + EOS를 빨리 뱉은 경우. 같은 모델도 실행마다
  편차가 크므로(예: SmolLM2 test1 38ms vs test3 5515ms) best-of-5 기준이다.
- VLM 4종(Cosmos 2B/8B, Qwen3-VL-2B, Qwen2.5-VL-3B)과 SmolVLM2는 첫 시도에서
  `pillow`/`torchvision`/`num2words` 누락으로 로드 실패 → `web.py` 의존성에
  추가 후 재측정해서 위 수치 확보. (커밋 안 된 변경: `web.py` inline deps)
- Nemotron-3-Nano-4B는 CUDA에서 `mamba_ssm` 없이도 로드·동작 확인.
