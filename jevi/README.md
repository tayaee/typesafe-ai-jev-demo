# jevi (제비) — jev clone using huggingface local model

A clone of the typesafe.ai Jev (SystemOne) protocol. `POST /v1/systemone`
takes `choice` / `noul` / `score` questions and judges them with a local
HF model. Output format is enforced by pydantic-ai.

## Run

```bash
export HF_TOKEN=hf_xxx     # only needed for gated models (Cosmos). Optional otherwise.
./web.sh list-models       # supported models
./web.sh run               # default model Qwen/Qwen3.5-2B, port 7001
./web.sh run --model test  # offline test backend, no weights
```

`web.bat` is the Windows launcher. See `web.py run --help` for host/port/hf-token options.

## Do I need HF_TOKEN?

No, except for `nvidia/Cosmos-Reason2-2B`, which is gated: accept its
license on the HF page and pass `--hf-token` (or set `HF_TOKEN`).
Qwen/Qwen3.5-2B and Nemotron 3 Nano 4B download fine without a token.
