# typesafe-ai-jev-demo

A collection of small apps for trying out [Typesafe.ai](https://typesafe.ai) features.

## Apps

| App | What it does | Docs |
| --- | --- | --- |
| [play-4096-jev](./play-4096-jev/) | Plays [4096](https://thereal4096.github.io) (a 2048 variant) via Playwright, asking the SystemOne judgment API (`jev-latest`) for the best move (`up` / `down` / `left` / `right`) until game over | [play-4096-jev/README.md](./play-4096-jev/README.md) |
| [play-4096-laya](./play-4096-laya/) | Same game, but the move is chosen locally by [Laya](https://github.com/receptron/laya) (open-source Jev-compatible System-1 model, ONNX Runtime, no API key) | [play-4096-laya/README.md](./play-4096-laya/README.md) |
| [korean-csat-2024-jev](./korean-csat-2024-jev/) | Solves Korean CSAT 2024 questions by asking the SystemOne judgment API (`jev-latest`) to pick one of 5 choices per question, then grades the answers | [korean-csat-2024-jev/README.md](./korean-csat-2024-jev/README.md) |
| [korean-csat-2024-laya](./korean-csat-2024-laya/) | Same exam, but each question is answered locally by [Laya](https://github.com/receptron/laya) (open-source Jev-compatible System-1 model, ONNX Runtime, no API key) | [korean-csat-2024-laya/README.md](./korean-csat-2024-laya/README.md) |
| [korean-csat-2024-jevi](./korean-csat-2024-jevi/) | Same exam, but each question is judged by the local [jevi](../jevi/) server (Jev-compatible SystemOne clone, default `http://localhost:7001`, no API key) | [korean-csat-2024-jevi/README.md](./korean-csat-2024-jevi/README.md) |

## Quick start

Each app is self-contained — see its own README for setup and usage. For example:

```bash
cd play-4096-jev
cp .env.template .env   # then put your TYPESAFE_API_KEY into .env
./run.sh
```
