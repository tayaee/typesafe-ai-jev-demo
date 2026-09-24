"""Pydantic models mirroring the Jev SystemOne HTTP contract.

Reference: https://docs.typesafe.ai/api
  Request  POST /v1/systemone  {state, model, questions}
  Response {model, answers, usage}

Question types: choice / noul / score. Answers carry the same ids as questions.
All response shapes are enforced again on the way out via TypeAdapter
(see judge.py), so the wire format can never drift from these models.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------- request side

CriteriaValue = Union[str, dict[str, Any], list[Any], None]
Instructions = Union[str, dict[str, Any], list[Any]]
State = Union[str, dict[str, Any], list[Any]]


class ChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    instructions: Instructions
    criteria: dict[str, CriteriaValue]

    @field_validator("criteria")
    @classmethod
    def _choice_bounds(cls, v: dict[str, CriteriaValue]) -> dict[str, CriteriaValue]:
        if not 1 <= len(v) <= 255:
            raise ValueError("choice criteria needs 1..255 options")
        return v


class NoulQuestion(BaseModel):
    type: Literal["noul"] = "noul"
    instructions: Instructions
    criteria: dict[str, CriteriaValue] | None = None


class ScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    instructions: Instructions
    criteria: list[CriteriaValue]

    @field_validator("criteria")
    @classmethod
    def _score_bounds(cls, v: list[CriteriaValue]) -> list[CriteriaValue]:
        if not 2 <= len(v) <= 10:
            raise ValueError("score criteria needs 2..10 levels")
        return v


Question = Union[ChoiceQuestion, NoulQuestion, ScoreQuestion]


class SystemOneRequest(BaseModel):
    state: State
    model: str = "jevi-latest"
    questions: dict[str, Question]

    @field_validator("questions")
    @classmethod
    def _non_empty(cls, v: dict[str, Question]) -> dict[str, Question]:
        if not v:
            raise ValueError("questions must not be empty")
        return v


# ---------------------------------------------------------------- answer side

class ChoiceAnswer(BaseModel):
    type: Literal["choice"] = "choice"
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check(self) -> "ChoiceAnswer":
        if self.choice not in self.probabilities:
            raise ValueError(f"choice {self.choice!r} not in probabilities")
        total = sum(self.probabilities.values())
        if abs(total - 1.0) > 1e-4:
            raise ValueError(f"probabilities must sum to 1 (got {total})")
        return self


class NoulAnswer(BaseModel):
    type: Literal["noul"] = "noul"
    noul: float = Field(ge=0.0, le=1.0)


class ScoreAnswer(BaseModel):
    type: Literal["score"] = "score"
    score: float
    legend: dict[str, str]
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check(self) -> "ScoreAnswer":
        if set(self.probabilities) != set(self.legend):
            raise ValueError("probabilities keys must match legend keys")
        total = sum(self.probabilities.values())
        if abs(total - 1.0) > 1e-4:
            raise ValueError(f"probabilities must sum to 1 (got {total})")
        if not (0 <= self.score <= len(self.legend) - 1):
            raise ValueError(f"score {self.score} out of legend range")
        return self


Answer = Union[ChoiceAnswer, NoulAnswer, ScoreAnswer]


class Usage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class SystemOneResponse(BaseModel):
    model: str
    answers: dict[str, Answer]
    usage: dict[str, int] | Usage

    @field_validator("usage", mode="before")
    @classmethod
    def _usage_coerce(cls, v: Any) -> Any:
        if isinstance(v, Usage):
            return {"input_tokens": v.input_tokens, "output_tokens": v.output_tokens}
        return v
