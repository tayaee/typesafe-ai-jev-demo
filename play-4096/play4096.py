# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Play 4096 (https://thereal4096.github.io) with the TypeSafe SystemOne judgment API.

Golden path (grilling Q1-Q5):
  Q1 API   : state={board,score} object + single `choice` question `best_move`
  Q2 env   : Playwright (external loop, API key stays server-side)
  Q3 read  : DOM `.tile-container .tile` parsing (tile-position-x-y + .tile-inner)
  Q4 move  : real keyboard path (ArrowUp/Right/Down/Left)
  Q5 scope : autoplay loop until game-over (use --max-moves N for single-demo)

Usage:
  uv run play4096.py [--connect INFO] [--url URL] [--new-game] [--start-delay-secs 10]
                     [--max-moves N] [--dry-run] [--move-delay-secs 0.0] [--headless]
                     [--typesafe-api-key KEY] [--corner CORNER]

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
    p.add_argument("--corner", default="lower-right",
                   choices=["upper-left", "upper-right", "lower-left", "lower-right"],
                   help="Corner to gather the largest tiles in (default: lower-right).")
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


def heuristic_move(board, corner: str = "lower-right") -> str | None:
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


def build_instructions(corner: str = "lower-right") -> str:
    descr = CORNER_DESCR.get(corner, CORNER_DESCR["lower-right"])
    return (
        "You play 4096 (a 2048 variant) on a 4x4 grid. Rows go top-to-bottom, "
        "columns left-to-right, 0 means empty. Merge equal tiles by sliding; "
        "after each slide a 2 or 4 appears. Keep the largest tile in the "
        f"{descr} and the board organized so it can keep merging toward 4096. "
        "Given the board, reply with exactly one of up/down/left/right: the best next slide."
    )


def build_criteria(corner: str = "lower-right") -> dict[str, str]:
    h_target = "right" if "right" in corner else "left"
    v_target = "down" if "lower" in corner else "up"
    descr = CORNER_DESCR.get(corner, CORNER_DESCR["lower-right"])
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


def call_systemone(board, score, api_url, api_key, model, timeout=30, corner: str = "lower-right"):
    state = {
        "game": "4096 (2048 variant), 4x4 grid, rows top-to-bottom, 0 = empty",
        "board": board,
        "score": score,
        "goal": "Merge tiles to reach 4096 and beyond without filling the board.",
        "strategy": f"Keep the largest tile in the {CORNER_DESCR.get(corner, corner)}.",
    }
    payload = {
        "state": state,
        "model": model,
        "questions": {
            "best_move": {
                "type": "choice",
                "instructions": build_instructions(corner),
                "criteria": build_criteria(corner),
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
        ans = data["answers"]["best_move"]
        choice = ans["choice"]
        probs = ans.get("probabilities", {})
        conf = ans.get("confidence")
    except Exception as e:
        raise RuntimeError(f"Bad SystemOne response: {raw[:500]} ({e})") from e
    if choice not in ("up", "down", "left", "right"):
        raise RuntimeError(f"Model returned invalid move {choice!r}: {raw[:500]}")
    return choice, probs, conf, dt_ms


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
                    print(f"[connect] unreadable {connect_path}: {e}; relaunching.")
            if info and info.get("cdp_url"):
                cdp = info["cdp_url"]
                print(f"[connect] attaching to {cdp} ...")
                browser = pw.chromium.connect_over_cdp(cdp)
                print("[connect] attached. (script exit will NOT kill this browser)")
            else:
                port = args.remote_debugging_port or find_free_port()
                profile = args.user_data_dir or (connect_path + ".profile")
                print(f"[launch] detached Chrome port={port} profile={profile} "
                      f"({'headed' if args.headed else 'headless'}) ...")
                cdp = launch_detached_chrome(profile, port, args.headed)
                info = {"cdp_url": cdp, "user_data_dir": profile}
                json.dump(info, open(connect_path, "w"), indent=2)
                print(f"[launch] wrote {connect_path}; re-run with the same --connect to reattach.")
                browser = pw.chromium.connect_over_cdp(cdp)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context(viewport=VIEWPORT)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.set_viewport_size(VIEWPORT)  # reattached tab keeps old size otherwise
            except Exception:
                pass
        else:
            print("[launch] ephemeral browser (no --connect; closes on exit) ...")
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
                print(f"[launch] channel=chrome failed ({e}); trying bundled chromium ...")
                browser = pw.chromium.launch(headless=not args.headed,
                                             args=launch_args)
            owns_browser = True
            ctx = browser.new_context(viewport=VIEWPORT)
            page = ctx.new_page()

        page.add_init_script(CONFIRM_OVERRIDE)
        print(f"[goto] {args.url}")
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[goto] warning: {e}")
        page.evaluate(CONFIRM_OVERRIDE)  # already-loaded page also needs it
        # NOTE: .tile-container is empty (hence hidden) until the first tiles
        # render, so wait for attached, not visible.
        page.wait_for_selector(".tile-container", state="attached", timeout=15000)
        page.wait_for_selector(".game-container", state="attached", timeout=15000)

        if args.new_game:
            print("[game] New Game")
            page.click(".restart-button")
            time.sleep(0.6)

        if args.start_delay_secs > 0:
            print(f"[wait] start in {args.start_delay_secs:.0f}s (--start-delay-secs) ...")
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
                print(f"[shot] failed: {e}")

        DIR = {"up": 0, "right": 1, "down": 2, "left": 3}
        moves = 0
        latencies: list[float] = []
        snap("move-000")
        while not STOP:
            board, score, over, won = wait_settled(page)
            if over:
                print(f"[over] game over after {moves} moves, score={score}\n{fmt_board(board)}")
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
                print(f"[over] no valid moves detected, score={score}\n{fmt_board(board)}")
                break

            if args.dry_run:
                move = heuristic_move(board, args.corner)
                probs, conf, dt = {}, None, 0.0
            else:
                try:
                    move, probs, conf, dt = call_systemone(
                        board, score, args.api_url, api_key, args.model, corner=args.corner)
                    latencies.append(dt)
                except Exception as e:
                    print(f"[api] {e}; heuristic fallback")
                    move, probs, conf, dt = heuristic_move(board, args.corner), {}, None, 0.0
                if move not in vm:
                    # model picked a dead direction: try next-best by probability
                    ordered = sorted(probs, key=lambda k: probs[k], reverse=True) if probs else []
                    alt = next((m for m in ordered + vm if m in vm and m != move), None)
                    print(f"[warn] model said {move} (no-op); trying {alt}")
                    move = alt or heuristic_move(board, args.corner)

            print(f"[move {moves+1}] board score={score}\n{fmt_board(board)}")
            print(f"  -> {move} " + (f"({dt:.0f}ms conf={conf} probs={probs})"
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
                  f"avg_latency={avg:.0f}ms min={min(latencies):.0f}ms max={max(latencies):.0f}ms")
        else:
            print(f"[stats] moves={moves} (no API calls)")
        snap("final")
        return 0
    finally:
        # Never kill a --connect browser: just detach. Ephemeral: close.
        try:
            if connect_path:
                pw.stop()
                print(f"[exit] detached; browser stays alive. "
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
