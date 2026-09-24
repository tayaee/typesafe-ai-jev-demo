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
    task: str = "text-generation"  # transformers pipeline task (VLMs: image-text-to-text)


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
        task="image-text-to-text",
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
    # --- NVIDIA edge: smaller / reasoning ---
    ModelSpec(
        hf_id="nvidia/Llama-3.1-Nemotron-Nano-4B-v1.1",
        params="4B",
        gated=False,
        trust_remote_code=False,
        vram="~9GB (bf16) / Jetson, single RTX",
        recommended=False,
        note="NVIDIA edge reasoning text model (Llama-3.1 based, 128K ctx). "
        "NVIDIA Open Model License.",
    ),
    ModelSpec(
        hf_id="nvidia/Cosmos-Reason2-8B",
        params="8.77B",
        gated=True,
        trust_remote_code=True,
        vram="~18GB (bf16) / AGX Orin+",
        recommended=False,
        note="Bigger Cosmos physical-AI VLM (Qwen3-VL-8B based, text queries OK). "
        "Accept the license on its HF page and pass --hf-token.",
        task="image-text-to-text",
    ),
    # --- China: Qwen tiny text ---
    ModelSpec(
        hf_id="Qwen/Qwen3-0.6B",
        params="0.6B",
        gated=False,
        trust_remote_code=False,
        vram="~1.5GB (bf16) / CPU (Q4 ~0.5GB)",
        recommended=False,
        note="Smallest Qwen3, CPU-runnable, 100+ langs. Apache 2.0.",
    ),
    ModelSpec(
        hf_id="Qwen/Qwen3-1.7B",
        params="1.7B",
        gated=False,
        trust_remote_code=False,
        vram="~4GB (bf16) / CPU (Q4)",
        recommended=False,
        note="Balanced tiny Qwen3, thinking/non-thinking modes. Apache 2.0.",
    ),
    ModelSpec(
        hf_id="Qwen/Qwen2.5-0.5B-Instruct",
        params="0.49B",
        gated=False,
        trust_remote_code=False,
        vram="~1GB / CPU proven",
        recommended=False,
        note="Smallest Qwen2.5 instruct, 29 langs incl. Korean. Apache 2.0.",
    ),
    # --- China: tiny VLMs (text queries OK) ---
    ModelSpec(
        hf_id="Qwen/Qwen3-VL-2B-Instruct",
        params="2B",
        gated=False,
        trust_remote_code=False,
        vram="~5GB (bf16)",
        recommended=False,
        note="Best tiny open VLM, 256K ctx. Apache 2.0.",
        task="image-text-to-text",
    ),
    ModelSpec(
        hf_id="Qwen/Qwen2.5-VL-3B-Instruct",
        params="3B",
        gated=False,
        trust_remote_code=False,
        vram="~6GB (bf16) / Orin Nano class (Q4)",
        recommended=False,
        note="Proven 3B VLM, needs transformers>=4.37. Apache 2.0.",
        task="image-text-to-text",
    ),
    ModelSpec(
        hf_id="OpenGVLab/InternVL3_5-1B-HF",
        params="1.1B",
        gated=False,
        trust_remote_code=True,
        vram="~2.5GB (bf16)",
        recommended=False,
        note="Smallest strong Chinese VLM. Apache 2.0.",
        task="image-text-to-text",
    ),
    ModelSpec(
        hf_id="OpenGVLab/InternVL3_5-2B-HF",
        params="2.3B",
        gated=False,
        trust_remote_code=True,
        vram="~5GB (bf16)",
        recommended=False,
        note="2B InternVL3.5, reasoning + GUI/embodied. Apache 2.0.",
        task="image-text-to-text",
    ),
    ModelSpec(
        hf_id="openbmb/MiniCPM-V-4_5",
        params="8.7B",
        gated=False,
        trust_remote_code=True,
        vram="~18GB (bf16) / 9GB (int4)",
        recommended=False,
        note="Top <=10B Chinese VLM (OpenCompass 77.0). Apache 2.0.",
        task="image-text-to-text",
    ),
    # --- CPU-tiny (HF Smol family) ---
    ModelSpec(
        hf_id="HuggingFaceTB/SmolLM2-1.7B-Instruct",
        params="1.7B",
        gated=False,
        trust_remote_code=False,
        vram="~3.5GB (bf16) / CPU (Q4)",
        recommended=False,
        note="CPU-friendly instruct + function calling. Apache 2.0, English-only.",
    ),
    ModelSpec(
        hf_id="HuggingFaceTB/SmolLM3-3B",
        params="3B",
        gated=False,
        trust_remote_code=False,
        vram="~6GB (bf16) / CPU (Q4)",
        recommended=False,
        note="3B SOTA, hybrid reasoning, 128K ctx. Needs transformers>=4.53. "
        "No Korean/Chinese.",
    ),
    ModelSpec(
        hf_id="HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
        params="0.5B",
        gated=False,
        trust_remote_code=False,
        vram="~1.2GB / CPU",
        recommended=False,
        note="Smallest video VLM, on-device. Apache 2.0.",
        task="image-text-to-text",
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
