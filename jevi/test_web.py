"""Tests for web.py / registry / local backend (no weights needed)."""

import json
import subprocess
import sys
from unittest.mock import patch

import pytest

import local_backend
from local_backend import HF_ENV, active_spec, extract_json
from models_registry import MODELS, resolve


def test_registry_has_all_three_plus_test():
    ids = {m.hf_id for m in MODELS}
    assert {
        "test",
        "Qwen/Qwen3.5-2B",
        "nvidia/Cosmos-Reason2-2B",
        "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16",
    } <= ids


def test_resolve_real_ids_case_insensitive():
    assert resolve("qwen/qwen3.5-2b").hf_id == "Qwen/Qwen3.5-2B"
    assert resolve("NVIDIA/cosmos-reason2-2b").hf_id == "nvidia/Cosmos-Reason2-2B"
    assert resolve("TEST").hf_id == "test"


def test_default_model_is_qwen():
    from models_registry import DEFAULT_MODEL

    assert resolve(DEFAULT_MODEL).hf_id == "Qwen/Qwen3.5-2B"


def test_resolve_unknown_raises_with_hint():
    with pytest.raises(KeyError, match="list-models"):
        resolve("gpt-99")


def test_active_spec_none_when_unset_or_test(monkeypatch):
    monkeypatch.delenv(HF_ENV, raising=False)
    assert active_spec() is None
    monkeypatch.setenv(HF_ENV, "test")
    assert active_spec() is None
    monkeypatch.setenv(HF_ENV, "no-such-model")
    assert active_spec() is None


def test_active_spec_resolves_without_loading(monkeypatch):
    monkeypatch.setenv(HF_ENV, "Qwen/Qwen3.5-2B")
    assert active_spec() is not None and active_spec().hf_id == "Qwen/Qwen3.5-2B"


def test_extract_json_from_noisy_output():
    out = 'Sure! Here it is:\n{"choice": "down", "probabilities": {"up": 0.1, "down": 0.9}} trailing'
    assert extract_json(out) == {"choice": "down", "probabilities": {"up": 0.1, "down": 0.9}}
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_choice_local_uses_model_json(monkeypatch):
    from judge import ChoiceQuestion

    q = ChoiceQuestion(
        instructions="Best slide?",
        criteria={"up": "go up", "down": "go down. Excellent."},
    )
    canned = json.dumps(
        {"choice": "down", "probabilities": {"up": 0.2, "down": 0.8}, "confidence": 0.7}
    )
    with patch.object(local_backend, "generate", return_value=canned):
        ans = local_backend.judge_choice_local("q", {"board": []}, q)
    assert ans.choice == "down" and ans.probabilities == {"up": 0.2, "down": 0.8}


def test_noul_score_local_fallback_on_garbage(monkeypatch):
    from judge import NoulQuestion, ScoreQuestion

    with patch.object(local_backend, "generate", return_value="garbage!!!"):
        n = local_backend.judge_noul_local("u", "help ASAP!", NoulQuestion(instructions="Urgent?"))
        assert n.type == "noul"
        s = local_backend.judge_score_local(
            "f", "payouts failing", ScoreQuestion(instructions="How mad?", criteria=["Calm", "Angry"])
        )
        assert set(s.probabilities) == {"0", "1"}


def test_server_models_lists_registry():
    from fastapi.testclient import TestClient

    from server import app

    ids = [m["id"] for m in TestClient(app).get("/v1/models").json()["models"]]
    assert {
        "jevi-latest",
        "test",
        "Qwen/Qwen3.5-2B",
        "nvidia/Cosmos-Reason2-2B",
        "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16",
    } <= set(ids)


def test_web_list_models_runs_without_heavy_deps():
    r = subprocess.run(
        [sys.executable, "web.py", "list-models"], capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, r.stderr
    assert "Qwen/Qwen3.5-2B" in r.stdout and "nvidia/Cosmos-Reason2-2B" in r.stdout


def test_new_small_models_resolve():
    for hid in [
        "nvidia/Llama-3.1-Nemotron-Nano-4B-v1.1",
        "nvidia/Cosmos-Reason2-8B",
        "Qwen/Qwen3-0.6B",
        "Qwen/Qwen3-1.7B",
        "Qwen/Qwen2.5-0.5B-Instruct",
        "Qwen/Qwen3-VL-2B-Instruct",
        "Qwen/Qwen2.5-VL-3B-Instruct",
        "OpenGVLab/InternVL3_5-1B-HF",
        "OpenGVLab/InternVL3_5-2B-HF",
        "openbmb/MiniCPM-V-4_5",
        "HuggingFaceTB/SmolLM2-1.7B-Instruct",
        "HuggingFaceTB/SmolLM3-3B",
        "HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
    ]:
        assert resolve(hid.lower()).hf_id == hid


def test_vlm_specs_use_image_text_task():
    vlm = {m.hf_id for m in MODELS if m.task == "image-text-to-text"}
    assert {
        "nvidia/Cosmos-Reason2-2B",
        "nvidia/Cosmos-Reason2-8B",
        "Qwen/Qwen3-VL-2B-Instruct",
        "Qwen/Qwen2.5-VL-3B-Instruct",
        "OpenGVLab/InternVL3_5-1B-HF",
        "OpenGVLab/InternVL3_5-2B-HF",
        "openbmb/MiniCPM-V-4_5",
        "HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
    } <= vlm
    text = {m.hf_id for m in MODELS if m.task == "text-generation"}
    assert {"Qwen/Qwen3-0.6B", "nvidia/Llama-3.1-Nemotron-Nano-4B-v1.1"} <= text


def test_generate_wraps_text_for_vlm_task(monkeypatch):
    import local_backend as lb

    calls: dict = {}

    class FakePipe:
        tokenizer = None

        def __call__(self, *a, **k):
            calls["args"] = a
            calls["kwargs"] = k
            return [{"generated_text": '{"noul": 0.5}'}]

    monkeypatch.setattr(lb, "_pipe", FakePipe())
    monkeypatch.setattr(lb, "_pipe_task", "image-text-to-text")
    assert lb.generate("hello") == '{"noul": 0.5}'
    assert calls["args"] == ()
    assert calls["kwargs"]["text"][0]["role"] == "user"


def test_generate_plain_string_for_text_task(monkeypatch):
    import local_backend as lb

    calls: dict = {}

    class FakePipe:
        tokenizer = None

        def __call__(self, *a, **k):
            calls["args"] = a
            calls["kwargs"] = k
            return [{"generated_text": "hi"}]

    monkeypatch.setattr(lb, "_pipe", FakePipe())
    monkeypatch.setattr(lb, "_pipe_task", "text-generation")
    assert lb.generate("hello") == "hi"
    assert calls["args"] == ("hello",)


def test_run_model_default_is_qwen():
    from web import build_parser

    assert build_parser().parse_args(["run"]).model == "Qwen/Qwen3.5-2B"


def test_web_run_unknown_model_fails_fast():
    r = subprocess.run(
        [sys.executable, "web.py", "run", "--model", "gpt-99"], capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 2 and "list-models" in r.stderr
