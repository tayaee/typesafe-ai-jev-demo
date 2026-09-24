"""jevi: mini webservice mimicking the Jev SystemOne protocol.

  POST /v1/systemone   {state, model, questions} -> {model, answers, usage}
  GET  /v1/models      registry model ids + active backend
  GET  /health         liveness probe

Question types (same names/shapes as https://docs.typesafe.ai/api):
  choice: {type, instructions, criteria: {option: description}}
  noul:   {type, instructions, criteria?: {true, false}}
  score:  {type, instructions, criteria: [level, ...]}

Run:
  ./web.sh run                                     # default model Qwen/Qwen3.5-2B
  ./web.sh run --model test                        # offline heuristic, no weights
  JEV_CLONE_MODEL=openai:gpt-4o-mini ./web.sh run  # remote LLM behind the same schema
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

import judge
from jev_models import SystemOneRequest, SystemOneResponse
from judge import state_text
from models_registry import MODELS

app = FastAPI(title="jevi", version="0.1.0")


def _active_backend() -> str:
    """Which judge actually answers: remote API model, local HF ref, or heuristic."""
    import local_backend

    remote = os.environ.get(judge.MODEL_ENV)
    if remote:
        return remote
    spec = local_backend.active_spec()
    if spec is not None:
        return spec.hf_id
    return "test"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
def list_models() -> dict:
    backend = _active_backend()
    return {
        "active_backend": backend,
        "models": [
            {"id": "jevi-latest", "backend": backend},  # Jev-compatible alias
            {"id": "jevi-1.0", "backend": backend},
            *[
                {
                    "id": m.hf_id,
                    "params": m.params,
                    "gated": m.gated,
                    "backend": backend,
                }
                for m in MODELS
            ],
        ],
    }


@app.post("/v1/systemone")
def systemone(req: SystemOneRequest) -> JSONResponse:
    answers = {qid: judge.judge_one(qid, q, req.state) for qid, q in req.questions.items()}
    input_tokens = judge.estimate_tokens(state_text(req.state))
    for qid, q in req.questions.items():
        input_tokens += judge.estimate_tokens(str(q.instructions)) + judge.estimate_tokens(
            str(q.criteria if getattr(q, "criteria", None) is not None else "")
        )
    usage = {"input_tokens": input_tokens, "output_tokens": 20 * len(answers)}
    # Final wire-format enforcement: the response itself must satisfy the schema.
    payload = SystemOneResponse(model=req.model, answers=answers, usage=usage)
    return JSONResponse(payload.model_dump())
