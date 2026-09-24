"""Local HF backend for jevi: run a registry model via transformers.

Heavy deps (transformers/torch) are imported lazily inside ``load()`` so
``import local_backend`` — and the whole test suite — works without them.

Answering strategy: prompt the model for ONLY a JSON object, extract it,
then clamp/renormalize exactly like the pydantic-ai LLM path and validate
through the same TypeAdapters. Any failure (bad JSON, OOM, ...) falls back
to the deterministic heuristic, so the wire format never breaks.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import judge
from judge import (
    ChoiceQuestion,
    NoulQuestion,
    ScoreQuestion,
    choice_adapter,
    confidence_of,
    describe,
    noul_adapter,
    score_adapter,
    state_text,
)
from models_registry import TEST_MODEL, ModelSpec, resolve

HF_ENV = "JEV_CLONE_HF_MODEL"
DEVICE_ENV = "JEV_CLONE_DEVICE"  # device_map override, e.g. cpu (default: auto)

_pipe = None
_pipe_id: str | None = None


def active_model_ref() -> str | None:
    return os.environ.get(HF_ENV) or None


def active_spec() -> ModelSpec | None:
    """Resolved spec to actually run, or None for unset/test/unknown.

    Unknown refs return None (fail-fast already happened in web.py);
    per-question judging then degrades to the heuristic instead of 500s.
    """
    ref = active_model_ref()
    if not ref:
        return None
    try:
        spec = resolve(ref)
    except KeyError:
        return None
    return None if spec.hf_id == TEST_MODEL else spec


def hf_token() -> str | None:
    for env in ("HF_TOKEN", "HF_HUB_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        if os.environ.get(env):
            return os.environ[env]
    return None


def load(model_ref: str):
    """Load (and cache) the transformers pipeline for a registry HF id.

    Fails fast with a human-readable error: web.py calls this at startup so
    a bad model/gated repo never becomes a silently-degraded server.
    """
    global _pipe, _pipe_id
    spec = resolve(model_ref)
    if spec.hf_id == TEST_MODEL:
        raise ValueError("--model test needs no weights (nothing to load)")
    if _pipe is not None and _pipe_id == spec.hf_id:
        return _pipe
    try:
        from transformers import pipeline
    except ImportError as e:
        raise RuntimeError("transformers/torch not installed. Run via `uv run web.py run ...`") from e
    try:
        _pipe = pipeline(
            "text-generation",
            model=spec.hf_id,
            trust_remote_code=spec.trust_remote_code,
            device_map=os.environ.get(DEVICE_ENV, "auto"),
            dtype="auto",
            token=hf_token(),
        )
    except Exception as e:
        raise RuntimeError(_load_hint(spec, e)) from e
    _pipe_id = spec.hf_id
    return _pipe


def _load_hint(spec: ModelSpec, e: Exception) -> str:
    msg = str(e)
    if spec.gated or "gated" in msg.lower() or "401" in msg or "403" in msg:
        return (
            f"Cannot load gated repo {spec.hf_id}: {msg}\n"
            f"1) Accept the license at https://huggingface.co/{spec.hf_id}\n"
            "2) Retry with --hf-token $HF_TOKEN (or $HF_TOKEN env)"
        )
    if "mamba" in msg.lower():
        return (
            f"Cannot load {spec.hf_id} (Mamba hybrid): {msg}\n"
            "On CUDA install: pip install mamba_ssm causal_conv1d ; "
            "on CPU-only hosts prefer --model Qwen/Qwen3.5-2B"
        )
    return f"Cannot load {spec.hf_id}: {msg}"


def generate(prompt: str, max_new_tokens: int = 256) -> str:
    if _pipe is None:
        raise RuntimeError("local model not loaded (call load() first)")
    try:
        eos = _pipe.tokenizer.eos_token_id
        out = _pipe(
            prompt,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            return_full_text=False,
            pad_token_id=eos,
        )
    except Exception as e:
        raise RuntimeError(f"generation failed: {e}") from e
    return out[0]["generated_text"]


def extract_json(text: str) -> dict[str, Any]:
    """Cut the first {...} block out of free-form output and parse it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def _warn(qid: str, e: Exception) -> None:
    print(f"[local] question {qid!r}: {e} -> heuristic fallback", file=sys.stderr)


# ---------------------------------------------------------------- per-type judging


def _choice_prompt(state: judge.State, q: ChoiceQuestion) -> str:
    opts = json.dumps(q.criteria, ensure_ascii=False, default=str)
    return (
        "You are a calibrated classifier. Reply with ONLY a JSON object, no other text.\n"
        f"State: {state_text(state)}\n"
        f"Question: {describe(q.instructions)}\n"
        f"Options: {opts}\n"
        'Return exactly: {"choice": "<exactly one key from Options>", '
        '"probabilities": {"<key>": <0..1, all keys, sum to 1>}, "confidence": <0..1>}'
    )


def judge_choice_local(qid: str, state: judge.State, q: ChoiceQuestion):
    options = list(q.criteria)
    try:
        data = extract_json(generate(_choice_prompt(state, q)))
        probs = {k: max(0.0, float(data.get("probabilities", {}).get(k, 0.0))) for k in options}
        s = sum(probs.values()) or 1.0
        probs = {k: v / s for k, v in probs.items()}
        best = max(probs, key=lambda k: probs[k])
        conf = min(1.0, max(0.0, float(data.get("confidence", confidence_of(list(probs.values()))))))
        return choice_adapter.validate_python(
            {"type": "choice", "choice": best, "probabilities": probs, "confidence": conf}
        )
    except Exception as e:
        _warn(qid, e)
        return judge.judge_choice_heuristic(state, q)


def judge_noul_local(qid: str, state: judge.State, q: NoulQuestion):
    try:
        prompt = (
            "Answer yes/no as a calibrated probability. Reply with ONLY a JSON object, no other text.\n"
            f"State: {state_text(state)}\n"
            f"Question: {describe(q.instructions)}\n"
            f"Rubric: {json.dumps(q.criteria, ensure_ascii=False, default=str)}\n"
            'Return exactly: {"noul": <0 = no .. 1 = yes>}'
        )
        data = extract_json(generate(prompt))
        return noul_adapter.validate_python(
            {"type": "noul", "noul": min(1.0, max(0.0, float(data["noul"])))}
        )
    except Exception as e:
        _warn(qid, e)
        return judge.judge_noul_heuristic(state, q)


def judge_score_local(qid: str, state: judge.State, q: ScoreQuestion):
    n = len(q.criteria)
    try:
        prompt = (
            "Rate along the ordered levels below. Reply with ONLY a JSON object, no other text.\n"
            f"State: {state_text(state)}\n"
            f"Question: {describe(q.instructions)}\n"
            f"Levels: {json.dumps([describe(lv) for lv in q.criteria], ensure_ascii=False)}\n"
            'Return exactly: {"score": <0-based weighted level>, '
            '"probabilities": {"0": <p>, "1": <p>, ... (all levels, sum to 1)>}'
        )
        data = extract_json(generate(prompt))
        probs = {str(i): max(0.0, float(data.get("probabilities", {}).get(str(i), 0.0))) for i in range(n)}
        s = sum(probs.values()) or 1.0
        probs = {k: v / s for k, v in probs.items()}
        score = min(n - 1.0, max(0.0, float(data.get("score", sum(i * p for i, p in enumerate(probs.values()))))))
        legend = {str(i): describe(lv) for i, lv in enumerate(q.criteria)}
        return score_adapter.validate_python(
            {
                "type": "score",
                "score": score,
                "legend": legend,
                "probabilities": probs,
                "confidence": round(confidence_of(list(probs.values())), 6),
            }
        )
    except Exception as e:
        _warn(qid, e)
        return judge.judge_score_heuristic(state, q)
