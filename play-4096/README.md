# typesafe-ai-jev-demo

Play [4096](https://thereal4096.github.io) (a 2048 variant) with the TypeSafe SystemOne judgment API (`jev-latest`).

`play4096.py` reads the board from the DOM, asks SystemOne for the best move (`up` / `down` / `left` / `right`), and presses the corresponding arrow key via Playwright until game over.

## Setup

Needs: `uv` (https://docs.astral.sh/uv/getting-started/installation/)

```bash
cp .env.template .env   # then put your key into .env
```

API key priority: `--typesafe-api-key KEY` > `$TYPESAFE_API_KEY` > `.env`.

The browser window is shown by default; pass `--headless` to hide it
(e.g. on servers without a display).

## Usage

```bash
./run.sh --help
./run.sh
./run.sh --move-delay-secs 0.4
```

Windows:

```bat
run.bat
```

## Tested on

- Windows
- WSL2 (Ubuntu)

Note (WSL2): the script looks for a `google-chrome` binary for `--connect` mode. It is **not** installed by default on WSL2 — install Google Chrome yourself, or just run without `--connect` (Playwright-provided browser).
