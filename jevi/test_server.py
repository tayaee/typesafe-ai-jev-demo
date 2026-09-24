"""Tests for jevi: protocol shapes + the two repo golden paths (4096, CSAT)."""

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)

BOARD_STATE = {
    "game": "4096 (2048 variant), 4x4 grid, rows top-to-bottom, 0 = empty",
    "board": [[128, 64, 32, 16], [0, 0, 0, 8], [0, 0, 0, 4], [0, 0, 0, 2]],
    "score": 1234,
    "goal": "Merge tiles to reach 4096.",
    "strategy": "Keep the largest tile in the lower-left corner.",
}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_models():
    ids = [m["id"] for m in client.get("/v1/models").json()["models"]]
    assert "jevi-latest" in ids


def test_choice_4096_shape():
    """Same shape as play-4096-jev/play4096.py: dict state + best_move choice."""
    r = client.post(
        "/v1/systemone",
        json={
            "state": BOARD_STATE,
            "model": "jevi-latest",
            "questions": {
                "best_move": {
                    "type": "choice",
                    "instructions": "Given the board, reply with the best next slide.",
                    "criteria": {
                        "up": "Slide all tiles up.",
                        "down": "Slide all tiles down toward the lower-left corner. Excellent.",
                        "left": "Slide all tiles left toward the lower-left corner. Excellent.",
                        "right": "Slide all tiles right.",
                    },
                }
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ans = body["answers"]["best_move"]
    assert ans["choice"] in ("up", "down", "left", "right")
    assert abs(sum(ans["probabilities"].values()) - 1.0) < 1e-4
    assert 0.0 <= ans["confidence"] <= 1.0
    assert body["usage"]["input_tokens"] > 0


def test_choice_combo_ids_with_plus():
    """Combo ids like 'down+left' (used by --combo mode) must pass through."""
    r = client.post(
        "/v1/systemone",
        json={
            "state": BOARD_STATE,
            "model": "jevi-latest",
            "questions": {
                "best_combo": {
                    "type": "choice",
                    "instructions": "Pick exactly one combo.",
                    "criteria": {
                        "down+left": "main loop into the corner",
                        "right+left": "emergency sidestep",
                        "up+down": "forced recovery",
                    },
                }
            },
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["answers"]["best_combo"]["choice"] in ("down+left", "right+left", "up+down")


def test_noul_ping_shape():
    """Same shape as play-4096-jev/ping.sh: string state + noul urgency."""
    r = client.post(
        "/v1/systemone",
        json={
            "state": "Hi, I've been trying to connect my Stripe account for 3 days. Please help ASAP.",
            "model": "jevi-latest",
            "questions": {"urgency": {"type": "noul", "instructions": "Does this message express urgency?"}},
        },
    )
    assert r.status_code == 200, r.text
    ans = r.json()["answers"]["urgency"]
    assert ans["type"] == "noul" and 0.0 <= ans["noul"] <= 1.0


def test_score_shape():
    r = client.post(
        "/v1/systemone",
        json={
            "state": "Help! My payouts have been failing for 3 days.",
            "model": "jevi-latest",
            "questions": {
                "frustration": {
                    "type": "score",
                    "instructions": "How frustrated is the customer?",
                    "criteria": ["Calm", "Frustrated", "Very angry"],
                }
            },
        },
    )
    assert r.status_code == 200, r.text
    ans = r.json()["answers"]["frustration"]
    assert set(ans["probabilities"]) == set(ans["legend"]) == {"0", "1", "2"}
    assert 0 <= ans["score"] <= 2


def test_multi_question_csat_shape():
    """Same shape as korean-csat-2024-jev/csat.py: string state + 5-way choice."""
    state = "[문제]\n다음 중 옳은 것은?\n\n[보기]\n① 사과 ② 바나나 ③ 체리 ④ 포도 ⑤ 사과와 바나나"
    r = client.post(
        "/v1/systemone",
        json={
            "model": "jevi-latest",
            "state": state,
            "questions": {
                "answer": {
                    "type": "choice",
                    "instructions": "위 문제의 정답으로 가장 적절한 보기를 반드시 하나만 고르시오.",
                    "criteria": {"1": "사과", "2": "바나나", "3": "체리", "4": "포도", "5": "사과와 바나나"},
                }
            },
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["answers"]["answer"]["choice"] in ("1", "2", "3", "4", "5")


def test_mixed_batch():
    r = client.post(
        "/v1/systemone",
        json={
            "state": "My payouts have been failing for 3 days, I want a refund.",
            "model": "jevi-latest",
            "questions": {
                "department": {
                    "type": "choice",
                    "instructions": "Which team?",
                    "criteria": {"billing": "money", "technical": "bugs"},
                },
                "urgent": {"type": "noul", "instructions": "Urgent?"},
                "frustration": {
                    "type": "score",
                    "instructions": "How frustrated?",
                    "criteria": ["Calm", "Angry"],
                },
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["answers"]) == {"department", "urgent", "frustration"}
    assert body["model"] == "jevi-latest"


def test_validation_errors():
    # empty questions
    assert client.post("/v1/systemone", json={"state": "x", "model": "m", "questions": {}}).status_code == 422
    # unknown type
    r = client.post(
        "/v1/systemone",
        json={"state": "x", "model": "m", "questions": {"q": {"type": "nope", "instructions": "?"}}},
    )
    assert r.status_code == 422
    # score with 1 level
    r = client.post(
        "/v1/systemone",
        json={
            "state": "x",
            "model": "m",
            "questions": {"q": {"type": "score", "instructions": "?", "criteria": ["only"]}},
        },
    )
    assert r.status_code == 422
