"""Judging backend for jevi.

Two paths, one format guarantee:

1. LLM path (optional): when ``JEV_CLONE_MODEL`` is set (e.g.
   ``openai:gpt-4o-mini``, ``ollama:qwen3.5:2b``), each question is answered
   by a ``pydantic_ai.Agent`` whose ``output_type`` is the matching verdict
   model below. pydantic-ai validates the model output against that schema
   (with retries), so free-form text can never leak onto the wire.

2. Heuristic path (default, offline): a deterministic token-overlap scorer
   builds the same verdict dicts, which are then validated through
   ``pydantic.TypeAdapter`` — the same validation engine pydantic-ai uses
   for its ``output_type`` — so the format is enforced even with no LLM.

3. Local HF path: when ``JEV_CLONE_HF_MODEL`` is set (see web.py --model),
   a registry model runs locally via transformers (local_backend.py).
   The model is asked for ONLY a JSON object, which is clamped/renormalized
   and validated through the same TypeAdapters; per-question failures fall
   back to the heuristic so the wire format never breaks.

Dispatch order: remote pydantic-ai LLM -> local HF -> heuristic.
Either way the response answers always satisfy jev_models.Answer.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter
from pydantic_ai import Agent

from jev_models import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
    State,
)

TOKEN_RE = re.compile(r"[a-z0-9가-힣]+")

MODEL_ENV = "JEV_CLONE_MODEL"


# ---------------------------------------------------------------- verdict schemas (pydantic-ai output types)


class ChoiceVerdict(BaseModel):
    """LLM output contract for a choice question."""

    choice: str = Field(description="Exactly one key from the given options")
    probabilities: dict[str, float] = Field(description="All options, summing to 1")
    confidence: float = Field(ge=0.0, le=1.0)


class NoulVerdict(BaseModel):
    """LLM output contract for a noul question."""

    noul: float = Field(ge=0.0, le=1.0, description="P(yes): 0=no, 1=yes")


class ScoreVerdict(BaseModel):
    """LLM output contract for a score question."""

    score: float = Field(description="Probability-weighted level, 0-based")
    probabilities: dict[str, float] = Field(description="Level index (as string) -> prob")


choice_adapter: TypeAdapter[ChoiceAnswer] = TypeAdapter(ChoiceAnswer)
noul_adapter: TypeAdapter[NoulAnswer] = TypeAdapter(NoulAnswer)
score_adapter: TypeAdapter[ScoreAnswer] = TypeAdapter(ScoreAnswer)


# ---------------------------------------------------------------- text helpers


def state_text(state: State) -> str:
    if isinstance(state, str):
        return state
    return json.dumps(state, ensure_ascii=False)


def describe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def overlap(a: list[str], b: set[str]) -> int:
    return sum(1 for t in a if t in b)


def softmax(xs: list[float], temperature: float = 1.0) -> list[float]:
    m = max(xs)
    exps = [math.exp((x - m) / temperature) for x in xs]
    s = sum(exps)
    return [e / s for e in exps]


def confidence_of(probs: list[float]) -> float:
    """Spread-based confidence like Jev: 0 for uniform, 1 for one-hot."""
    k = len(probs)
    if k <= 1:
        return 1.0
    return (max(probs) - 1.0 / k) / (1.0 - 1.0 / k)


# Words the prompt author uses to mark good/bad options (e.g. the 4096
# corner strategy writes "Excellent: pushes tiles toward the corner").
# Lets the heuristic follow rubric sentiment when the state itself is
# numeric (game boards) and shares no tokens with the criteria.
POS_WORDS = {"excellent", "best", "prefer", "correct", "recommended", "ideal", "good", "great"}
NEG_WORDS = {"bad", "avoid", "poor", "wrong", "never"}


def sentiment_bonus(description: str) -> float:
    toks = tokens(description)
    return sum(1.0 for t in toks if t in POS_WORDS) - sum(1.0 for t in toks if t in NEG_WORDS)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ---------------------------------------------------------------- heuristic path


def judge_choice_heuristic(state: State, q: ChoiceQuestion) -> ChoiceAnswer:
    st = tokens(state_text(state))
    instr = set(tokens(describe(q.instructions)))
    raw: list[float] = []
    for i, (key, desc) in enumerate(q.criteria.items()):
        key_toks = set(tokens(key.replace("_", " ")))
        desc_text = describe(desc)
        desc_toks = set(tokens(desc_text))
        s = 2.0 * overlap(st, key_toks | desc_toks) + 0.5 * overlap(st, instr)
        s += sentiment_bonus(desc_text)
        s += (len(q.criteria) - i) * 1e-6  # deterministic tie-break
        raw.append(s)
    probs = softmax(raw)
    options = list(q.criteria)
    best = options[probs.index(max(probs))]
    return choice_adapter.validate_python(
        {
            "type": "choice",
            "choice": best,
            "probabilities": {k: round(p, 6) for k, p in zip(options, probs)},
            "confidence": round(confidence_of(probs), 6),
        }
    )


def judge_noul_heuristic(state: State, q: NoulQuestion) -> NoulAnswer:
    st = set(tokens(state_text(state)))
    instr = set(tokens(describe(q.instructions)))
    crit = q.criteria or {}
    yes_hint = set(tokens(describe(crit.get("true", ""))))
    no_hint = set(tokens(describe(crit.get("false", ""))))
    yes = overlap(list(st), instr | yes_hint)
    no = overlap(list(st), no_hint)
    if yes == 0 and no == 0:
        return noul_adapter.validate_python({"type": "noul", "noul": 0.5})
    p_yes = softmax([float(yes), float(no)])[0]
    return noul_adapter.validate_python({"type": "noul", "noul": round(p_yes, 6)})


def judge_score_heuristic(state: State, q: ScoreQuestion) -> ScoreAnswer:
    st = tokens(state_text(state))
    instr = set(tokens(describe(q.instructions)))
    raw: list[float] = []
    for i, level in enumerate(q.criteria):
        lvl = set(tokens(describe(level)))
        s = 2.0 * overlap(st, lvl) + 0.5 * overlap(st, instr)
        s += (len(q.criteria) - i) * 1e-6
        raw.append(s)
    probs = softmax(raw)
    score = sum(i * p for i, p in enumerate(probs))
    legend = {str(i): describe(level) for i, level in enumerate(q.criteria)}
    return score_adapter.validate_python(
        {
            "type": "score",
            "score": round(score, 6),
            "legend": legend,
            "probabilities": {str(i): round(p, 6) for i, p in enumerate(probs)},
            "confidence": round(confidence_of(probs), 6),
        }
    )


# ---------------------------------------------------------------- LLM path (pydantic-ai format enforcement)


def _llm_model() -> str | None:
    return os.environ.get(MODEL_ENV) or None


def _prompt(state: State, instructions: Any, criteria: Any) -> str:
    return (
        "State to evaluate:\n"
        f"{state_text(state)}\n\n"
        f"Question: {describe(instructions)}\n"
        f"Options/rubric (JSON): {json.dumps(criteria, ensure_ascii=False, default=str)}\n\n"
        "Reply with exactly the requested structured output. "
        "Probabilities must sum to 1."
    )


def judge_choice_llm(state: State, q: ChoiceQuestion, model: str) -> ChoiceAnswer:
    agent: Agent[None, ChoiceVerdict] = Agent(
        model, output_type=ChoiceVerdict, retries=2,
        system_prompt="You are a calibrated classifier. Output valid structured data only.",
    )
    options = list(q.criteria)
    res = agent.run_sync(_prompt(state, q.instructions, q.criteria))
    out = res.output
    if out.choice not in q.criteria:  # clamp stray keys, renormalize
        out.choice = options[0]
    probs = {k: max(0.0, float(out.probabilities.get(k, 0.0))) for k in options}
    s = sum(probs.values()) or 1.0
    probs = {k: v / s for k, v in probs.items()}
    best = max(probs, key=lambda k: probs[k])
    return choice_adapter.validate_python(
        {
            "type": "choice",
            "choice": best,
            "probabilities": probs,
            "confidence": min(1.0, max(0.0, float(out.confidence))),
        }
    )


def judge_noul_llm(state: State, q: NoulQuestion, model: str) -> NoulAnswer:
    agent: Agent[None, NoulVerdict] = Agent(
        model, output_type=NoulVerdict, retries=2,
        system_prompt="You answer yes/no as a calibrated probability. Output valid structured data only.",
    )
    res = agent.run_sync(_prompt(state, q.instructions, q.criteria))
    return noul_adapter.validate_python({"type": "noul", "noul": float(res.output.noul)})


def judge_score_llm(state: State, q: ScoreQuestion, model: str) -> ScoreAnswer:
    agent: Agent[None, ScoreVerdict] = Agent(
        model, output_type=ScoreVerdict, retries=2,
        system_prompt="You rate along ordered levels. Output valid structured data only.",
    )
    res = agent.run_sync(_prompt(state, q.instructions, q.criteria))
    out = res.output
    n = len(q.criteria)
    probs = {str(i): max(0.0, float(out.probabilities.get(str(i), 0.0))) for i in range(n)}
    s = sum(probs.values()) or 1.0
    probs = {k: v / s for k, v in probs.items()}
    score = min(n - 1.0, max(0.0, float(out.score)))
    legend = {str(i): describe(level) for i, level in enumerate(q.criteria)}
    return score_adapter.validate_python(
        {
            "type": "score",
            "score": score,
            "legend": legend,
            "probabilities": probs,
            "confidence": round(confidence_of(list(probs.values())), 6),
        }
    )


# ---------------------------------------------------------------- dispatch


def judge_one(qid: str, q: ChoiceQuestion | NoulQuestion | ScoreQuestion, state: State):
    """Judge a single question: remote LLM -> local HF -> heuristic.

    Every return value has passed a TypeAdapter validation (pydantic-ai's
    Agent(output_type=...) on the remote path, the same adapters on the
    local/heuristic paths), so the output format is enforced on all paths.
    """
    model = _llm_model()
    try:
        if model and isinstance(q, ChoiceQuestion):
            return judge_choice_llm(state, q, model)
        if model and isinstance(q, NoulQuestion):
            return judge_noul_llm(state, q, model)
        if model and isinstance(q, ScoreQuestion):
            return judge_score_llm(state, q, model)
    except Exception:
        pass  # fall through to local backend, then heuristic
    try:
        import local_backend

        if local_backend.active_spec() is not None:
            if isinstance(q, ChoiceQuestion):
                return local_backend.judge_choice_local(qid, state, q)
            if isinstance(q, NoulQuestion):
                return local_backend.judge_noul_local(qid, state, q)
            return local_backend.judge_score_local(qid, state, q)
    except Exception:
        pass  # fall through to deterministic heuristic
    if isinstance(q, ChoiceQuestion):
        return judge_choice_heuristic(state, q)
    if isinstance(q, NoulQuestion):
        return judge_noul_heuristic(state, q)
    return judge_score_heuristic(state, q)
