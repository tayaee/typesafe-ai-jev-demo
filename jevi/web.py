# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "fastapi>=0.115",
#   "uvicorn>=0.30",
#   "pydantic>=2.7",
#   "pydantic-ai-slim>=2.0",
#   "httpx>=0.27",
#   "transformers>=4.55",
#   "accelerate",
#   "huggingface_hub",
#   "torch",
# ]
# ///
"""jevi launcher: serve the Jev-protocol clone backed by a local HF model.

  uv run web.py list-models
  uv run web.py run [--model <HF-id|test>] [--host 0.0.0.0] [--port 7001] [--hf-token $HF_TOKEN]

--model takes a real HF repo id as shown by list-models (no aliases),
or "test" for the offline protocol-testing backend.
Omitted --model defaults to Qwen/Qwen3.5-2B.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models_registry import DEFAULT_MODEL, TEST_MODEL, resolve  # noqa: E402


def cmd_list_models(_args: argparse.Namespace) -> int:
    rows = [("hf repo", "params", "gated", "note"), *_table()]
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    for n, r in enumerate(rows):
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
        if n == 0:
            print("  ".join("-" * w for w in widths))
    print(f"\nrun default: uv run web.py run   (= --model {DEFAULT_MODEL})")
    return 0


def _table() -> list[tuple[str, str, str, str]]:
    from models_registry import table_rows

    return table_rows()


def cmd_run(args: argparse.Namespace) -> int:
    try:
        spec = resolve(args.model)
    except KeyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    token = args.hf_token or os.environ.get("HF_TOKEN")
    if token:
        for env in ("HF_TOKEN", "HF_HUB_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
            os.environ[env] = token
    if spec.gated and not token:
        print(
            f"WARNING: {spec.hf_id} is gated and no --hf-token was given. "
            "Accept the license at https://huggingface.co/"
            f"{spec.hf_id} and retry with --hf-token $HF_TOKEN.",
            file=sys.stderr,
        )

    if spec.hf_id != TEST_MODEL:
        import local_backend

        os.environ[local_backend.HF_ENV] = spec.hf_id
        print(f"[web] loading {spec.hf_id} ...", flush=True)
        try:
            local_backend.load(spec.hf_id)
        except (RuntimeError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print("[web] model ready", flush=True)
    else:
        print("[web] test backend (offline heuristic, no weights)", flush=True)

    import uvicorn

    print(f"[web] serving on {args.host}:{args.port} (POST /v1/systemone)", flush=True)
    uvicorn.run("server:app", host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="web.py", description="Serve jevi with a local HF model.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-models", help="Show the recommended local models.")
    r = sub.add_parser("run", help="Load a model and serve POST /v1/systemone.")
    r.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Real HF repo id or 'test' (default: {DEFAULT_MODEL}).",
    )
    r.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    r.add_argument("--port", type=int, default=7001, help="Bind port (default: 7001).")
    r.add_argument(
        "--hf-token", default=os.environ.get("HF_TOKEN"),
        help="HF token for gated repos (default: $HF_TOKEN).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "list-models":
        return cmd_list_models(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
