# play-4096-laya — 4096 player powered by local Laya

Play [4096](https://thereal4096.github.io) (a 2048 variant) via Playwright,
asking a **local** [Laya](https://github.com/receptron/laya) System-1 decision
model (open-source, Jev-compatible, ONNX Runtime) for the best move until game
over. No API key, no game-data network calls after the one-time weight
download.

Sibling: [`../play-4096-jev/`](../play-4096-jev/) plays the same game through
the TypeSafe SystemOne (`jev-latest`) HTTP API. Game loop, prompts, and combo
strategy are kept identical so the two backends are comparable.

## Setup

Needs: Node.js 20+ and `npm`.

```bash
cd play-4096-laya
npm install
```

First run downloads the ONNX weights (~1.7 GB, fp32) from Hugging Face and
caches them under `~/.cache/receptron-laya` (override with `LAYA_CACHE`, or
point `--model-dir` at a local export from `export/export_onnx.py`). Budget
~2 GB RAM for the loaded model. `npx playwright install chromium` is only
needed if no system Chrome exists — by default the script reuses system
Chrome (`channel: "chrome"`).

Local model bundle without downloading:

```bash
LAYA_MODEL_DIR=./onnx npm start -- --dry-run --help
```

## Usage

```bash
npm start -- --help
npm start -- --dry-run --max-moves 2 --start-delay-secs 0 --new-game
npm start -- --new-game --start-delay-secs 10
npm start -- --connect .browser.json --new-game --shot-dir ./shots
npm start -- --connect .browser.json --headless --shot-dir ./shots
```

`./run.sh` / `run.bat` are thin wrappers that `npm install` on first run and
forward all args to `src/play4096-laya.ts` via `tsx`:

```bash
./run.sh --dry-run --max-moves 2 --start-delay-secs 0 --new-game
```

Windows:

```bat
run.bat --dry-run --max-moves 2 --start-delay-secs 0 --new-game
```

Key flags (same semantics as `play-4096-jev`): `--connect [FILE]`
(persistent Chrome reuse; missing file → detached Chrome is launched),
`--no-combo` (single `best_move` instead of the default multi-key
`best_combo`), `--combos "down+left,..."` (max 10 × 4 keys), `--corner
lower-left|lower-right|upper-left|upper-right`, `--model-dir DIR`,
`--dry-run` (heuristic only — no model load/download), `--verbose`.

## Tested on

- Linux (Node 20+)
