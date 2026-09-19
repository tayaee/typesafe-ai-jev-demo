# 4096 player powered by typesafe.ai

Play [4096](https://thereal4096.github.io) (a 2048 variant) with the TypeSafe SystemOne judgment API (`jev-latest`).

## Setup

Needs: `uv` (https://docs.astral.sh/uv/getting-started/installation/)

```bash
cp .env.template .env   # then put your key into .env
```

API key priority: `--typesafe-api-key KEY` > `$TYPESAFE_API_KEY` > `.env`.

## Usage

```bash
./run.sh
./run.sh --move-delay-secs 0.4
```

Windows:

```bat
run.bat
run.bat --move-delay-secs 0.4
```

## Tested on

- Windows
- WSL2 (Ubuntu)
