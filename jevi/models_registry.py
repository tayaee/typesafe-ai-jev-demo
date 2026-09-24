"""Model registry for jevi: real HF repo ids + the offline "test" model.

Single source of truth shared by web.py (list-models/run) and the server.
``resolve()`` accepts a real HF repo id (case-insensitive) or "test".
There are no aliases: --model takes exactly what list-models shows.
"""

from __future__ import annotations

from dataclasses import dataclass

TEST_MODEL = "test"  # protocol-testing model: offline heuristic, no download
DEFAULT_MODEL = "Qwen/Qwen3.5-2B"  # used when --model is omitted


@dataclass(frozen=True)
class ModelSpec:
    hf_id: str  # real Hugging Face repo id, or "test"
    params: str  # human-readable size
    gated: bool  # needs license accept + --hf-token
    trust_remote_code: bool
    vram: str  # rough requirement
    recommended: bool
    note: str  # why this model


MODELS: list[ModelSpec] = [
    ModelSpec(
        hf_id=TEST_MODEL,
        params="0",
        gated=False,
        trust_remote_code=False,
        vram="none",
        recommended=False,
        note="Offline deterministic scorer, no download. For protocol tests/CI.",
    ),
    ModelSpec(
        hf_id="Qwen/Qwen3.5-2B",
        params="2.27B",
        gated=False,
        trust_remote_code=True,
        vram="~6GB (bf16) / ~2GB (4bit)",
        recommended=True,
        note="RECOMMENDED. Smartest <=2B open-weight (2026-09). Apache 2.0.",
    ),
    ModelSpec(
        hf_id="nvidia/Cosmos-Reason2-2B",
        params="2.44B",
        gated=True,
        trust_remote_code=True,
        vram="~6GB (bf16)",
        recommended=False,
        note="Strict <=2B NVIDIA edge model (physical-AI VLM, text queries OK). "
        "Accept the license on its HF page and pass --hf-token.",
    ),
    ModelSpec(
        hf_id="nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16",
        params="3.97B",
        gated=False,
        trust_remote_code=False,
        vram="~9GB (bf16) / Jetson Thor, Orin Nano 8GB (Q4)",
        recommended=False,
        note="Strongest NVIDIA edge text model (over the 2B budget). "
        "Mamba hybrid: on CUDA you may need mamba_ssm + causal_conv1d.",
    ),
]


def resolve(name: str) -> ModelSpec:
    """Resolve a real HF repo id (case-insensitive) or "test" to a ModelSpec."""
    key = name.strip().lower()
    for m in MODELS:
        if key == m.hf_id.lower():
            return m
    valid = ", ".join(m.hf_id for m in MODELS)
    raise KeyError(f"Unknown model {name!r}. See `web.py list-models`. Valid: {valid}")


def table_rows() -> list[tuple[str, str, str, str]]:
    return [(m.hf_id, m.params, "yes" if m.gated else "no", m.note) for m in MODELS]
