# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Play 4096 (https://thereal4096.github.io) with the TypeSafe SystemOne judgment API.

Golden path (grilling Q1-Q5):
  Q1 API   : state={board,score} object + `choice` question `best_combo`
             (multi-key sequence, ON by default; --no-combo for single best_move)
  Q2 env   : Playwright (external loop, API key stays server-side)
  Q3 read  : DOM `.tile-container .tile` parsing (tile-position-x-y + .tile-inner)
  Q4 move  : real keyboard path (ArrowUp/Right/Down/Left)
  Q5 scope : autoplay loop until game-over (use --max-moves N for single-demo)

Usage:
  uv run play4096.py [--connect INFO] [--url URL] [--new-game] [--start-delay-secs 10]
                     [--max-moves N] [--dry-run] [--move-delay-secs 0.0] [--headless]
                     [--typesafe-api-key KEY] [--corner CORNER]
                     [--no-combo] [--combos "down+left,down+down+left,right+left,up+down"]
                     [--verbose]

  Combo mode is ON by default (one API call -> key sequence pressed at once).
  Use --no-combo for single-key mode.

API key (priority order):
  1. --typesafe-api-key KEY (alias: --api-key)
  2. $TYPESAFE_API_KEY environment variable
  3. TYPESAFE_API_KEY entry in a .env file (cwd or script dir)
  Copy .env.template to .env and fill in your key. --dry-run skips the API (heuristic).

Browser persistence:
  --connect FILE  JSON file holding {"cdp_url": ..., "user_data_dir": ...}.
                  * File missing -> detached Chrome is launched (survives script
                    exit), its endpoint is written to FILE.
                  * File exists  -> connect_over_cdp to the running Chrome.
                  So: run once, Ctrl-C / normal exit (browser is left alive),
                  run again with the same --connect FILE to reattach.
  No --connect   -> ephemeral Playwright browser, closed on exit.

API (same shape as a1.sh):
  POST https://api.typesafe.ai/v1/systemone
  {"state": {"board": [[..]], "score": N, ...}, "model": "jev-latest",
   "questions": {"best_move": {"type": "choice", "instructions": ...,
                                "criteria": {"up":..,"down":..,"left":..,"right":..}}}}
  Key from --typesafe-api-key (alias --api-key), $TYPESAFE_API_KEY, or .env.
  --dry-run skips the API (heuristic).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

STOP = False


def load_dotenv(paths: list[str] | None = None) -> None:
    """Load KEY=VALUE lines from .env file(s) into os.environ (no override).

    Default search: .env in cwd, then .env next to this script.
    No third-party dependency on purpose (keeps `uv run` deps minimal).
    """
    if paths is None:
        here = os.path.dirname(os.path.abspath(__file__))
        paths = [os.path.join(os.getcwd(), ".env"), os.path.join(here, ".env")]
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[len("export "):].strip()
                    if "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    if not key or key in os.environ:
                        continue
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                        value = value[1:-1]
                    os.environ[key] = value
        except FileNotFoundError:
            continue
        except OSError:
            continue


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Play 4096 with TypeSafe SystemOne (choice/best_move).")
    p.add_argument("--connect", nargs="?", const=".play4096-browser.json", default=None,
                   help="Path to browser-info JSON for persistent Chrome reuse. "
                        "Missing file -> launch detached Chrome and write it; "
                        "existing file -> attach to the running Chrome.")
    p.add_argument("--url", default="https://thereal4096.github.io",
                   help="Game page URL.")
    p.add_argument("--new-game", action="store_true",
                   help="Click New Game before starting.")
    p.add_argument("--start-delay-secs", type=float, default=2.0,
                   help="Wait this long before the first move (watch/countdown).")
    p.add_argument("--max-moves", type=int, default=None,
                   help="Stop after N moves (default: until game over).")
    p.add_argument("--dry-run", action="store_true",
                   help="No API call; use a local heuristic (for wiring tests).")
    p.add_argument("--move-delay-secs", type=float, default=0.0,
                   help="Extra settle delay after each move (0 = fastest; "
                        "use 0.4 for a watchable speed).")
    p.add_argument("--user-data-dir", default=None,
                   help="Chrome profile dir for --connect launches "
                        "(default: <connect-file>.profile).")
    p.add_argument("--remote-debugging-port", type=int, default=0,
                   help="Fixed CDP port for --connect launches (default: auto free port).")
    p.add_argument("--headed", dest="headed", action="store_true", default=True,
                     help="Show the browser window (default: shown).")
    p.add_argument("--headless", dest="headed", action="store_false",
                     help="Run headless, no window (e.g. servers without display).")
    p.add_argument("--model", default="jev-latest", help="SystemOne model.")
    p.add_argument("--typesafe-api-key", "--api-key", dest="api_key", default=None,
                   help="TypeSafe API key (default: $TYPESAFE_API_KEY or .env file).")
    p.add_argument("--api-url", default="https://api.typesafe.ai/v1/systemone")
    p.add_argument("--shot-dir", default=None,
                   help="Save a PNG screenshot per move here (to watch the run).")
    p.add_argument("--corner", default="lower-left",
                   choices=["upper-left", "upper-right", "lower-left", "lower-right"],
                   help="Corner to gather the largest tiles in (default: lower-left).")
    p.add_argument("--combo", dest="combo", action="store_true", default=True,
                   help="Multi-key mode: one API call recommends a key sequence "
                        "(e.g. down+left) and the browser presses all keys at once. "
                        "Default: ON.")
    p.add_argument("--no-combo", dest="combo", action="store_false",
                   help="Disable multi-key mode; fall back to single-key best_move.")
    p.add_argument("--combos", default=None,
                   help="Custom combo list, comma-separated, each '+'-joined, "
                        "max 10 combos x max 4 keys "
                        "(default: corner-aware 10 combos; "
                        'e.g. --combos "down+left,down+down+left,right+left,up+down"). '
                        "Implies --combo.")
    p.add_argument("--verbose", action="store_true",
                   help="Verbose logging: board dumps + full probs/timings. "
                        "Default: one line per move "
                        "([move ###] board score=###, typesafe.ai decision (#.### sec) "
                        "=> <seq> prob #.##).")
    return p.parse_args()


# ---------------------------------------------------------------- board logic

POS_RE = re.compile(r"tile-position-(\d+)-(\d+)")

STATE_JS = """() => {
  const tiles = [...document.querySelectorAll('.tile-container .tile')].map(el => ({
    cls: el.className,
    text: (el.querySelector('.tile-inner') || {}).textContent || ''
  }));
  const sc = document.querySelector('.score-container');
  let score = 0;
  if (sc) {
    const first = sc.firstChild;
    const raw = (first && first.textContent ? first.textContent : sc.textContent) || '0';
    score = parseInt(raw.replace(/[^0-9-]/g, ''), 10) || 0;
  }
  const msg = document.querySelector('.game-message');
  return {
    tiles, score,
    over: !!(msg && msg.classList.contains('game-over')),
    won: !!(msg && msg.classList.contains('game-won'))
  };
}"""


def snapshot(page) -> tuple[list[list[int]], int, bool, bool]:
    """Read (board, score, over, won) from the DOM. Duplicates -> keep max."""
    data = page.evaluate(STATE_JS)
    board = [[0] * 4 for _ in range(4)]  # board[row][col], row 0 = top
    for t in data.get("tiles", []):
        m = POS_RE.search(t.get("cls", ""))
        if not m:
            continue
        x, y = int(m.group(1)) - 1, int(m.group(2)) - 1
        if not (0 <= x < 4 and 0 <= y < 4):
            continue
        try:
            v = int((t.get("text") or "").strip())
        except ValueError:
            continue
        if v > board[y][x]:
            board[y][x] = v
    return board, int(data.get("score", 0)), bool(data.get("over")), bool(data.get("won"))


def board_key(board) -> tuple:
    return tuple(v for row in board for v in row)


def wait_settled(page, timeout=2.5) -> tuple[list[list[int]], int, bool, bool]:
    """Poll until the board fingerprint is stable twice (merge animation)."""
    prev = None
    stable = 0
    deadline = time.time() + timeout
    last = ([[0] * 4 for _ in range(4)], 0, False, False)
    while time.time() < deadline and not STOP:
        last = snapshot(page)
        k = (board_key(last[0]), last[1])
        if k == prev:
            stable += 1
            if stable >= 2:
                return last
        else:
            stable = 0
            prev = k
        time.sleep(0.1)
    return last


def fmt_board(board) -> str:
    return "\n".join(" ".join(f"{v:5d}" for v in row) for row in board)


def fmt_prob(probs: dict, key: str) -> str:
    """Format probs[key] as #.##, '--' when unavailable (dry-run/fallback)."""
    try:
        v = probs.get(key) if isinstance(probs, dict) else None
        return f"{float(v):.2f}" if v is not None else "--"
    except (TypeError, ValueError):
        return "--"


def fmt_move_line(n: int, score: int, seq: str, probs: dict | None = None,
                 dt_ms: float = 0.0) -> str:
    try:
        sec = f"{float(dt_ms) / 1000:.3f} sec"
    except (TypeError, ValueError):
        sec = "-- sec"
    return (f"[move {n:03d}] board score={score}, typesafe.ai decision ({sec}) => "
            f"{seq} prob {fmt_prob(probs or {}, seq)}")


def fmt_usage(usage: dict | None) -> str:
    """Format usage.input_tokens as in=123tok, 'in=--' when unavailable."""
    try:
        v = (usage or {}).get("input_tokens")
        return f"in={int(v)}tok" if v is not None else "in=--"
    except (TypeError, ValueError):
        return "in=--"


# --- 2048 slide simulation (dry-run validity filter) ---

def _slide_row_left(row: list[int]) -> list[int]:
    tiles = [v for v in row if v]
    out: list[int] = []
    i = 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            out.append(tiles[i] * 2)
            i += 2
        else:
            out.append(tiles[i])
            i += 1
    return out + [0] * (4 - len(out))


def moved_board(board: list[list[int]], move: str) -> list[list[int]]:
    """Board as it would look after `move` ignoring the random new tile."""
    b = [r[:] for r in board]
    if move == "left":
        return [_slide_row_left(r) for r in b]
    if move == "right":
        return [list(reversed(_slide_row_left(list(reversed(r))))) for r in b]
    # vertical: transpose, slide, transpose back
    t = [list(c) for c in zip(*b)]
    if move == "up":
        t = [_slide_row_left(r) for r in t]
    else:  # down
        t = [list(reversed(_slide_row_left(list(reversed(r))))) for r in t]
    return [list(r) for r in zip(*t)]


def valid_moves(board) -> list[str]:
    return [m for m in ("up", "right", "down", "left") if moved_board(board, m) != board]


def heuristic_move(board, corner: str = "lower-left") -> str | None:
    """Corner-weighted fallback; used for --dry-run and API failure."""
    vm = valid_moves(board)
    if not vm:
        return None
    # Weight grows exponentially toward the target corner so that merges
    # pulling big tiles into the corner score highest.
    def weight(y: int, x: int) -> int:
        tx = (3 - x) if "left" in corner else x
        ty = (3 - y) if "upper" in corner else y
        return 2 ** (tx + ty)

    def score(b: list[list[int]]) -> tuple[int, int]:
        s = sum(v * weight(y, x) for y, row in enumerate(b) for x, v in enumerate(row))
        empty = sum(1 for row in b for v in row if v == 0)
        return (s, empty)

    h_target = "right" if "right" in corner else "left"
    v_target = "down" if "lower" in corner else "up"
    h_avoid = "left" if h_target == "right" else "right"
    v_avoid = "up" if v_target == "down" else "down"
    preference = (h_target, v_target, h_avoid, v_avoid)
    return max(vm, key=lambda m: (score(moved_board(board, m)), -preference.index(m)))


# ---------------------------------------------------------------- API

CORNER_DESCR = {
    "upper-left": "upper-left corner (top row, leftmost column)",
    "upper-right": "upper-right corner (top row, rightmost column)",
    "lower-left": "lower-left corner (bottom row, leftmost column)",
    "lower-right": "lower-right corner (bottom row, rightmost column)",
}


def build_instructions(corner: str = "lower-left") -> str:
    descr = CORNER_DESCR.get(corner, CORNER_DESCR["lower-left"])
    return (
        "You play 4096 (a 2048 variant) on a 4x4 grid. Rows go top-to-bottom, "
        "columns left-to-right, 0 means empty. Merge equal tiles by sliding; "
        "after each slide a 2 or 4 appears. Keep the largest tile in the "
        f"{descr} and the board organized so it can keep merging toward 4096. "
        "If the rows near the corner are full and sorted descending toward it, "
        "merge the stack above the edge column downward first; "
        "do not shuffle the sorted rows. "
        "Given the board, reply with exactly one of up/down/left/right: the best next slide."
    )


def build_criteria(corner: str = "lower-left") -> dict[str, str]:
    h_target = "right" if "right" in corner else "left"
    v_target = "down" if "lower" in corner else "up"
    descr = CORNER_DESCR.get(corner, CORNER_DESCR["lower-left"])
    base = {
        "up": "Slide all tiles up.",
        "right": "Slide all tiles right.",
        "down": "Slide all tiles down.",
        "left": "Slide all tiles left.",
    }
    criteria: dict[str, str] = {}
    for move, text in base.items():
        if move in (h_target, v_target):
            criteria[move] = f"{text} Excellent: pushes tiles toward the {descr}."
        else:
            criteria[move] = f"{text} Usually bad: moves tiles away from the {descr}."
    return criteria


MOVE_CRITERIA = build_criteria()

INSTRUCTIONS = build_instructions()


# ---------------------------------------------------------------- combos (multi-key sequences)

VALID_MOVES = ("up", "right", "down", "left")
MAX_COMBOS = 10
MAX_SEQ_LEN = 4


def combo_specs(corner: str = "lower-left") -> list[tuple[str, list[str], str]]:
    """Default 10 corner-aware sequences for 4096 strategy (each 1-4 keys).

    lower-left corner example:
      1. down+left                 : 주력 — 모서리로 모으는 기본 왕복
      2. left+down                 : 주력 변형 — 가로 먼저 합친 뒤 아래로
      3. down+down+left            : 많이 쓰임 — 세로로 두 번 눌러 합친 뒤 모서리로
      4. left+left+down            : 가로로 두 번 합친 뒤 아래로
      5. down+left+down+left       : 주력 2회 반복 (4키)
      6. down+down+left+left       : 세로+가로 정리 (4키)
      7. right+left                : down이 막혔을 때 긴급 — 오른쪽으로 틀었다 즉시 복귀
      8. right+left+down           : 긴급 수평 왕복 후 아래로 모서리 복귀
      9. up+down                   : 불가피하게 up을 눌렀으면 반드시 즉시 down 복구
     10. up+down+left              : 강제 up 복구 후 왼쪽으로 모서리 복귀
    Other corners mirror h/v targets (e.g. lower-right -> down+right ...).
    """
    h_target = "right" if "right" in corner else "left"
    v_target = "down" if "lower" in corner else "up"
    h_avoid = "left" if h_target == "right" else "right"
    v_avoid = "up" if v_target == "down" else "down"
    return [
        (f"{v_target}+{h_target}", [v_target, h_target],
         f"{v_target} then {h_target}: main loop, gather into the corner."),
        (f"{h_target}+{v_target}", [h_target, v_target],
         f"{h_target} then {v_target}: main-loop variant, merge rows first."),
        (f"{v_target}+{v_target}+{h_target}", [v_target, v_target, h_target],
         f"{v_target} twice then {h_target}: merge vertically, then gather. "
         f"Sorted-board cleanup: merges the stack above the edge column into it."),
        (f"{h_target}+{h_target}+{v_target}", [h_target, h_target, v_target],
         f"{h_target} twice then {v_target}: merge horizontally, then gather."),
        (f"{v_target}+{h_target}+{v_target}+{h_target}",
         [v_target, h_target, v_target, h_target],
         f"{v_target}-{h_target} twice: double main loop without new API call. "
         f"Best pick when the two corner rows are full and sorted: merges the edge-column "
         f"stack, then the row pair beside the corner, then drops, keeping sorted rows intact."),
        (f"{v_target}+{v_target}+{h_target}+{h_target}",
         [v_target, v_target, h_target, h_target],
         f"2x {v_target} then 2x {h_target}: full tidy into the corner."),
        (f"{h_avoid}+{h_target}", [h_avoid, h_target],
         f"{h_avoid} then {h_target}: emergency when {v_target} is blocked, return at once."),
        (f"{h_avoid}+{h_target}+{v_target}", [h_avoid, h_target, v_target],
         f"{h_avoid} then {h_target} then {v_target}: emergency sidestep, then corner."),
        (f"{v_avoid}+{v_target}", [v_avoid, v_target],
         f"{v_avoid} then {v_target}: only when forced {v_avoid}, restore immediately."),
        (f"{v_avoid}+{v_target}+{h_target}", [v_avoid, v_target, h_target],
         f"{v_avoid} then {v_target} then {h_target}: forced {v_avoid} recovery into corner."),
    ]


def parse_combos_arg(s: str) -> list[tuple[str, list[str]]]:
    """Parse --combos string into [(combo_id, [moves])]. Max 10 combos x 4 keys."""
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts:
        raise ValueError("--combos is empty")
    if len(parts) > MAX_COMBOS:
        raise ValueError(f"--combos takes at most {MAX_COMBOS} sequences (got {len(parts)})")
    out: list[tuple[str, list[str]]] = []
    for p in parts:
        seq = [k.strip().lower() for k in re.split(r"[+\s>]+", p) if k.strip()]
        if not seq:
            raise ValueError(f"empty sequence in --combos: {p!r}")
        if len(seq) > MAX_SEQ_LEN:
            raise ValueError(f"sequence {p!r} exceeds max {MAX_SEQ_LEN} keys")
        for k in seq:
            if k not in VALID_MOVES:
                raise ValueError(f"invalid move {k!r} in --combos (use up/down/left/right)")
        out.append(("+".join(seq), seq))
    # dedupe preserving order
    seen: dict[str, list[str]] = {}
    for cid, seq in out:
        seen.setdefault(cid, seq)
    return list(seen.items())


def resolve_combos(args) -> list[tuple[str, list[str]]]:
    """Return active combo list from --combos or corner-aware defaults."""
    if args.combos:
        return [(cid, seq) for cid, seq in parse_combos_arg(args.combos)]
    return [(cid, seq) for cid, seq, _ in combo_specs(args.corner)]


def build_combo_instructions(corner: str = "lower-left",
                             specs: list[tuple[str, list[str], str]] | None = None) -> str:
    specs = specs if specs is not None else combo_specs(corner)
    descr = CORNER_DESCR.get(corner, CORNER_DESCR["lower-left"])
    h_target = "right" if "right" in corner else "left"
    v_target = "down" if "lower" in corner else "up"
    h_avoid = "left" if h_target == "right" else "right"
    opts = ", ".join(f"{cid} (= {' then '.join(seq)})" for cid, seq, _ in specs)
    return (
        "You play 4096 (a 2048 variant) on a 4x4 grid. Rows go top-to-bottom, "
        "columns left-to-right, 0 means empty. Merge equal tiles by sliding; "
        "after each slide a 2 or 4 appears. Keep the largest tile in the "
        f"{descr} and the board organized so it can keep merging toward 4096. "
        "Sorted-board rule: if the two rows nearest the corner are full and sorted "
        "descending toward the corner, prefer "
        f"{v_target}+{h_target}+{v_target}+{h_target} or {v_target}+{v_target}+{h_target}: "
        "they merge the tiles stacked above the edge column into it, then merge the row pair "
        "beside the corner, then drop the result, without shuffling the sorted rows. "
        f"Never lead with {h_avoid} when the corner row is full: "
        "it drags the largest tile out of the corner. "
        f"Given the board, reply with exactly one of: {opts}. "
        "The browser will press the keys in that sequence at once, in order."
    )


def build_combo_criteria(corner: str = "lower-left",
                         specs: list[tuple[str, list[str], str]] | None = None) -> dict[str, str]:
    specs = specs if specs is not None else combo_specs(corner)
    return {cid: f"Press {' then '.join(seq)} in order. {why}"
            for cid, seq, why in specs}


def apply_sequence(board: list[list[int]], seq: list[str]) -> list[list[int]]:
    """Simulate a key sequence ignoring random new tiles (no-op steps skipped)."""
    cur = [r[:] for r in board]
    for m in seq:
        nb = moved_board(cur, m)
        if nb != cur:
            cur = nb
    return cur


def heuristic_combo(board, corner: str = "lower-left",
                    specs: list[tuple[str, list[str]]] | None = None) -> str | None:
    """Corner-weighted fallback for combo mode; returns best combo_id."""
    seqs: list[tuple[str, list[str]]]
    if specs is not None:
        seqs = specs
    else:
        seqs = [(cid, seq) for cid, seq, _ in combo_specs(corner)]

    def weight(y: int, x: int) -> int:
        tx = (3 - x) if "left" in corner else x
        ty = (3 - y) if "upper" in corner else y
        return 2 ** (tx + ty)

    def score(b: list[list[int]]) -> tuple[int, int]:
        s = sum(v * weight(y, x) for y, row in enumerate(b) for x, v in enumerate(row))
        empty = sum(1 for row in b for v in row if v == 0)
        return (s, empty)

    best: str | None = None
    best_key = None
    for i, (cid, seq) in enumerate(seqs):
        final = apply_sequence(board, seq)
        if final == board:
            continue  # whole sequence is a no-op on this board
        k = (score(final), -i)
        if best_key is None or k > best_key:
            best_key, best = k, cid
    if best is None:
        # every combo is a no-op (rare): fall back to single-move heuristic
        single = heuristic_move(board, corner)
        if single is None:
            return None
        for cid, seq in seqs:
            if seq and seq[0] == single:
                return cid
        return seqs[0][0]
    return best


def _post_choice(state: dict, question_name: str, instructions: str,
                 criteria: dict[str, str], valid: set[str],
                 api_url: str, api_key: str, model: str, timeout: int = 30):
    """Shared SystemOne choice POST. Returns (choice, probs, conf, dt_ms, usage)."""
    payload = {
        "state": state,
        "model": model,
        "questions": {
            question_name: {
                "type": "choice",
                "instructions": instructions,
                "criteria": criteria,
            }
        },
    }
    body = json.dumps(payload).encode()
    t0 = time.perf_counter()
    req = urllib.request.Request(
        api_url, data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
    except Exception as e:
        raise RuntimeError(f"SystemOne request failed: {e}") from e
    dt_ms = (time.perf_counter() - t0) * 1000
    try:
        data = json.loads(raw)
        ans = data["answers"][question_name]
        choice = ans["choice"]
        probs = ans.get("probabilities", {})
        conf = ans.get("confidence")
        usage = data.get("usage", {}) or {}
    except Exception as e:
        raise RuntimeError(f"Bad SystemOne response: {raw[:500]} ({e})") from e
    if choice not in valid:
        raise RuntimeError(f"Model returned invalid choice {choice!r}: {raw[:500]}")
    return choice, probs, conf, dt_ms, usage


def call_systemone(board, score, api_url, api_key, model, timeout=30, corner: str = "lower-left"):
    state = {
        "game": "4096 (2048 variant), 4x4 grid, rows top-to-bottom, 0 = empty",
        "board": board,
        "score": score,
        "goal": "Merge tiles to reach 4096 and beyond without filling the board.",
        "strategy": f"Keep the largest tile in the {CORNER_DESCR.get(corner, corner)}.",
    }
    return _post_choice(state, "best_move", build_instructions(corner),
                        build_criteria(corner), {"up", "down", "left", "right"},
                        api_url, api_key, model, timeout)


def call_systemone_combo(board, score, api_url, api_key, model, timeout=30,
                         corner: str = "lower-left",
                         specs: list[tuple[str, list[str], str]] | None = None):
    """Ask for one of the multi-key combos. Returns (combo_id, seq, probs, conf, dt, usage)."""
    specs = specs if specs is not None else combo_specs(corner)
    state = {
        "game": "4096 (2048 variant), 4x4 grid, rows top-to-bottom, 0 = empty",
        "board": board,
        "score": score,
        "goal": "Merge tiles to reach 4096 and beyond without filling the board.",
        "strategy": f"Keep the largest tile in the {CORNER_DESCR.get(corner, corner)}. "
                    "Prefer 2-4 key sequences; the browser presses them in order at once.",
        "combos": {cid: "+".join(seq) for cid, seq, _ in specs},
    }
    choice, probs, conf, dt, usage = _post_choice(
        state, "best_combo", build_combo_instructions(corner, specs),
        build_combo_criteria(corner, specs), {cid for cid, _, _ in specs},
        api_url, api_key, model, timeout)
    seq = next(s for c, s, _ in specs if c == choice)
    return choice, seq, probs, conf, dt, usage


# ---------------------------------------------------------------- browser

def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_chrome_exe() -> str | None:
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            return pw.chromium.executable_path
    except Exception:
        return None


def wait_cdp(port: int, timeout: float = 30.0) -> str:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                json.loads(r.read().decode())
            return f"http://127.0.0.1:{port}"
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"Chrome CDP not ready on port {port}")


def launch_detached_chrome(user_data_dir: str, port: int, headed: bool) -> str:
    exe = find_chrome_exe()
    if not exe:
        raise RuntimeError("No Chrome/Chromium found (need google-chrome or playwright browsers).")
    os.makedirs(user_data_dir, exist_ok=True)
    cmd = [exe, f"--remote-debugging-port={port}",
           f"--user-data-dir={user_data_dir}",
           "--no-first-run", "--no-default-browser-check",
           "--disable-dev-shm-usage", "--no-sandbox",
           "--disable-search-engine-choice-screen",
           "about:blank"]
    if not headed:
        cmd.insert(1, "--headless=new")
        cmd.insert(2, "--disable-gpu")
    else:
        cmd.insert(1, f"--window-size={VIEWPORT['width']},{VIEWPORT['height'] + 100}")
    subprocess.Popen(cmd, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return wait_cdp(port)


# ---------------------------------------------------------------- main

KEYS = {"up": "ArrowUp", "right": "ArrowRight", "down": "ArrowDown", "left": "ArrowLeft"}

# Default Playwright viewport is 1280x720, which clips the 4096 board.
# Height x1.5 -> full board visible.
VIEWPORT = {"width": 1280, "height": 1080}

CONFIRM_OVERRIDE = "window.confirm = () => true;"


def main() -> int:
    global STOP
    args = parse_args()

    def vprint(*a, **k):
        if args.verbose:
            print(*a, **k)

    def on_sig(signum, frame):
        global STOP
        STOP = True
        print(f"\n[signal {signum}] graceful stop after current move...", flush=True)

    signal.signal(signal.SIGINT, on_sig)
    signal.signal(signal.SIGTERM, on_sig)

    load_dotenv()
    api_key = args.api_key or os.environ.get("TYPESAFE_API_KEY")
    if not args.dry_run and not api_key:
        print("ERROR: set $TYPESAFE_API_KEY, add TYPESAFE_API_KEY to .env "
              "(see .env.template), use --typesafe-api-key KEY, or use --dry-run.",
              file=sys.stderr)
        return 2

    combo_mode = bool(args.combo or args.combos)
    combo_full: list[tuple[str, list[str], str]] = []
    combo_by_id: dict[str, list[str]] = {}
    if combo_mode:
        try:
            if args.combos:
                parsed = parse_combos_arg(args.combos)
                combo_full = [(cid, seq, f"Custom sequence {cid}: press in order.")
                              for cid, seq in parsed]
            else:
                combo_full = combo_specs(args.corner)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        combo_by_id = {cid: seq for cid, seq, _ in combo_full}
        print(f"[combo] multi-key mode: {len(combo_full)} options, "
              f"{', '.join(cid for cid, _, _ in combo_full)}")
        print("[prompt] instructions:")
        print("  " + build_combo_instructions(args.corner, combo_full))
        print("[prompt] criteria:")
        for cid, seq, why in combo_full:
            print(f"  {cid}: {why}")
    else:
        print("[prompt] instructions:")
        print("  " + build_instructions(args.corner))
        print("[prompt] criteria:")
        for move, text in build_criteria(args.corner).items():
            print(f"  {move}: {text}")

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = None
    owns_browser = False  # ephemeral only; persistent Chrome is never killed
    connect_path = args.connect

    try:
        if connect_path:
            info = None
            if os.path.exists(connect_path):
                try:
                    info = json.load(open(connect_path))
                except Exception as e:
                    vprint(f"[connect] unreadable {connect_path}: {e}; relaunching.")
            if info and info.get("cdp_url"):
                cdp = info["cdp_url"]
                vprint(f"[connect] attaching to {cdp} ...")
                browser = pw.chromium.connect_over_cdp(cdp)
                vprint("[connect] attached. (script exit will NOT kill this browser)")
            else:
                port = args.remote_debugging_port or find_free_port()
                profile = args.user_data_dir or (connect_path + ".profile")
                vprint(f"[launch] detached Chrome port={port} profile={profile} "
                       f"({'headed' if args.headed else 'headless'}) ...")
                cdp = launch_detached_chrome(profile, port, args.headed)
                info = {"cdp_url": cdp, "user_data_dir": profile}
                json.dump(info, open(connect_path, "w"), indent=2)
                vprint(f"[launch] wrote {connect_path}; re-run with the same --connect to reattach.")
                browser = pw.chromium.connect_over_cdp(cdp)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context(viewport=VIEWPORT)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.set_viewport_size(VIEWPORT)  # reattached tab keeps old size otherwise
            except Exception:
                pass
        else:
            vprint("[launch] ephemeral browser (no --connect; closes on exit) ...")
            exe = find_chrome_exe()
            if exe and os.path.basename(exe).startswith("chrome-headless-shell"):
                exe = None  # bundled shell version skew; prefer system chrome below
            launch_args = ["--no-sandbox", "--disable-dev-shm-usage"]
            if args.headed:
                launch_args.append(f"--window-size={VIEWPORT['width']},{VIEWPORT['height'] + 100}")
            try:
                # Prefer system Chrome: no `playwright install` download needed.
                browser = pw.chromium.launch(headless=not args.headed, channel="chrome",
                                             args=launch_args)
            except Exception as e:
                vprint(f"[launch] channel=chrome failed ({e}); trying bundled chromium ...")
                browser = pw.chromium.launch(headless=not args.headed,
                                             args=launch_args)
            owns_browser = True
            ctx = browser.new_context(viewport=VIEWPORT)
            page = ctx.new_page()

        page.add_init_script(CONFIRM_OVERRIDE)
        vprint(f"[goto] {args.url}")
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            vprint(f"[goto] warning: {e}")
        page.evaluate(CONFIRM_OVERRIDE)  # already-loaded page also needs it
        # NOTE: .tile-container is empty (hence hidden) until the first tiles
        # render, so wait for attached, not visible.
        page.wait_for_selector(".tile-container", state="attached", timeout=15000)
        page.wait_for_selector(".game-container", state="attached", timeout=15000)

        if args.new_game:
            vprint("[game] New Game")
            page.click(".restart-button")
            time.sleep(0.6)

        if args.start_delay_secs > 0:
            vprint(f"[wait] start in {args.start_delay_secs:.0f}s (--start-delay-secs) ...")
            t_end = time.time() + args.start_delay_secs
            while time.time() < t_end and not STOP:
                time.sleep(0.2)

        if args.shot_dir:
            os.makedirs(args.shot_dir, exist_ok=True)

        def snap(tag: str):
            if not args.shot_dir:
                return
            try:
                page.screenshot(path=os.path.join(args.shot_dir, f"{tag}.png"))
            except Exception as e:
                vprint(f"[shot] failed: {e}")

        DIR = {"up": 0, "right": 1, "down": 2, "left": 3}
        moves = 0
        latencies: list[float] = []
        tok_total = 0
        ended_no_move = False
        snap("move-000")
        while not STOP:
            board, score, over, won = wait_settled(page)
            if over:
                print(f"[over] game over after {moves} moves, score={score}")
                vprint(fmt_board(board))
                ended_no_move = True
                break
            if won:
                # keep going past 4096 instead of stopping on the win banner
                try:
                    page.click(".keep-playing-button", timeout=2000)
                    time.sleep(0.4)
                    continue
                except Exception:
                    pass
            if args.max_moves is not None and moves >= args.max_moves:
                print(f"[done] max-moves={args.max_moves} reached, score={score}")
                break
            vm = valid_moves(board)
            if not vm:
                print(f"[over] no valid moves detected, score={score}")
                vprint(fmt_board(board))
                ended_no_move = True
                break

            seq_to_press: list[str] = []
            combo_id: str | None = None
            if combo_mode:
                combo_pairs = [(cid, seq) for cid, seq, _ in combo_full]
                if args.dry_run:
                    combo_id = heuristic_combo(board, args.corner, combo_pairs)
                    probs, conf, dt, usage = {}, None, 0.0, {}
                else:
                    try:
                        combo_id, seq, probs, conf, dt, usage = call_systemone_combo(
                            board, score, args.api_url, api_key, args.model,
                            corner=args.corner, specs=combo_full)
                        latencies.append(dt)
                        try:
                            tok_total += int((usage or {}).get("input_tokens") or 0)
                        except (TypeError, ValueError):
                            pass
                    except Exception as e:
                        vprint(f"[api] {e}; heuristic fallback")
                        combo_id = heuristic_combo(board, args.corner, combo_pairs)
                        probs, conf, dt, usage = {}, None, 0.0, {}
                    if combo_id is None or apply_sequence(board, combo_by_id[combo_id]) == board:
                        ordered = sorted(probs, key=lambda k: probs[k], reverse=True) if probs else []
                        alt = next((c for c in ordered + [c for c, _ in combo_pairs]
                                    if c != combo_id and c in combo_by_id
                                    and apply_sequence(board, combo_by_id[c]) != board), None)
                        vprint(f"[warn] combo {combo_id} is no-op; trying {alt}")
                        combo_id = alt or heuristic_combo(board, args.corner, combo_pairs)
                if combo_id is None:
                    print(f"[over] no effective combo, score={score}")
                    vprint(fmt_board(board))
                    ended_no_move = True
                    break
                seq_to_press = combo_by_id[combo_id]
                print(fmt_move_line(moves + 1, score, combo_id, probs, dt))
                if args.verbose:
                    print(fmt_board(board))
                    print(f"  -> {combo_id} ({'+'.join(seq_to_press)}) " + (
                        f"({dt:.0f}ms conf={conf} {fmt_usage(usage)} probs={probs})"
                        if not args.dry_run else "(dry-run)"))
                for step in seq_to_press:
                    if STOP:
                        break
                    if args.max_moves is not None and moves >= args.max_moves:
                        break
                    cur, _, _, _ = snapshot(page)
                    page.keyboard.press(KEYS[step])
                    moves += 1
                    time.sleep(max(0.05, args.move_delay_secs))
                    deadline = time.time() + 1.5
                    while time.time() < deadline and not STOP:
                        nb, _, _, _ = snapshot(page)
                        if board_key(nb) != board_key(cur):
                            break
                        time.sleep(0.08)
                if args.max_moves is not None and moves >= args.max_moves:
                    print(f"[done] max-moves={args.max_moves} reached, score={score}")
                    break
                snap(f"move-{moves:03d}")
                continue

            if args.dry_run:
                move = heuristic_move(board, args.corner)
                probs, conf, dt, usage = {}, None, 0.0, {}
            else:
                try:
                    move, probs, conf, dt, usage = call_systemone(
                        board, score, args.api_url, api_key, args.model, corner=args.corner)
                    latencies.append(dt)
                    try:
                        tok_total += int((usage or {}).get("input_tokens") or 0)
                    except (TypeError, ValueError):
                        pass
                except Exception as e:
                    vprint(f"[api] {e}; heuristic fallback")
                    move, probs, conf, dt, usage = heuristic_move(board, args.corner), {}, None, 0.0, {}
                if move not in vm:
                    # model picked a dead direction: try next-best by probability
                    ordered = sorted(probs, key=lambda k: probs[k], reverse=True) if probs else []
                    alt = next((m for m in ordered + vm if m in vm and m != move), None)
                    vprint(f"[warn] model said {move} (no-op); trying {alt}")
                    move = alt or heuristic_move(board, args.corner)

            print(fmt_move_line(moves + 1, score, move, probs, dt))
            if args.verbose:
                print(fmt_board(board))
                print(f"  -> {move} " + (f"({dt:.0f}ms conf={conf} {fmt_usage(usage)} probs={probs})"
                                         if not args.dry_run else "(dry-run)"))
            page.keyboard.press(KEYS[move])
            moves += 1
            time.sleep(max(0.05, args.move_delay_secs))
            # wait until the board actually changes (or timeout -> re-read)
            deadline = time.time() + 3.0
            while time.time() < deadline and not STOP:
                nb, _, _, _ = snapshot(page)
                if board_key(nb) != board_key(board):
                    break
                time.sleep(0.1)
            snap(f"move-{moves:03d}")

        if latencies:
            avg = sum(latencies) / len(latencies)
            print(f"[stats] moves={moves} api_calls={len(latencies)} "
                  f"avg_latency={avg:.0f}ms min={min(latencies):.0f}ms max={max(latencies):.0f}ms "
                  f"input_tokens={tok_total}")
        else:
            print(f"[stats] moves={moves} (no API calls)")
        snap("final")
        if ended_no_move and not STOP:
            try:
                input("[exit] no more moves - press enter to exit")
            except (EOFError, KeyboardInterrupt):
                pass
        return 0
    finally:
        # Never kill a --connect browser: just detach. Ephemeral: close.
        try:
            if connect_path:
                pw.stop()
                vprint(f"[exit] detached; browser stays alive. "
                       f"Reattach: uv run play4096.py --connect {connect_path}")
            else:
                if browser and owns_browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
                pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
