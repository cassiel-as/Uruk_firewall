"""CLI for the bounded small-task executor."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.small_task_executor import profile_summary, run_small_task


def _read_text(args: argparse.Namespace) -> str:
    if args.text:
        return " ".join(args.text)
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a low-level task via the task-aware local worker policy.")
    parser.add_argument("text", nargs="*", help="Input text. Reads stdin when omitted.")
    parser.add_argument(
        "--task",
        default="classify",
        choices=[
            "classify",
            "extract_json",
            "normalize_json",
            "summarize",
            "compress_context",
            "extract_entities",
            "rewrite_query",
            "answer_simple",
        ],
        help="Low-level task to run.",
    )
    parser.add_argument("--root", default=".", help="Repository root containing config/nodes.yaml.")
    parser.add_argument("--profile", default="auto", help="Task profile name or auto.")
    parser.add_argument("--json", action="store_true", help="Print full JSON result.")
    parser.add_argument("--profile-summary", action="store_true", help="Print configured small profile and exit.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    config_dir = root / "config"

    if args.profile_summary:
        print(json.dumps(profile_summary(config_dir, args.profile), ensure_ascii=False, indent=2))
        return 0

    text = _read_text(args)
    if not text.strip():
        parser.error("text is required via args or stdin")

    result = asyncio.run(
        run_small_task(
            args.task,
            text,
            config_dir=config_dir,
            profile_name=args.profile,
        )
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if result.get("ok") else "FALLBACK"
        print(
            f"URUK small task {status}: {result.get('task')} "
            f"via {result.get('source')} "
            f"({result.get('provider')}/{result.get('model')})"
        )
        if result.get("text"):
            print(result["text"])
        if result.get("error"):
            print(f"error: {result['error']}")
        for warning in result.get("warnings") or []:
            print(f"warning: {warning}")

    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
