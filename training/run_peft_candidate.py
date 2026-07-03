"""Run a trained PEFT adapter as an URUK controller candidate."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.run_controller_candidate import (  # noqa: E402
    DEFAULT_DATASET_DIR,
    load_examples,
)
from training.peft_controller_runtime import PeftControllerRuntime  # noqa: E402


DEFAULT_ADAPTER = ROOT / "training" / "artifacts" / "uruk-controller-qwen3-1.7b-lora"
DEFAULT_OUTPUT = ROOT / "training" / "predictions" / "peft_controller_test.jsonl"


def run_peft_candidate(
    *,
    adapter: Path = DEFAULT_ADAPTER,
    base_model: str = "Qwen/Qwen3-1.7B",
    dataset: Path = DEFAULT_DATASET_DIR,
    output: Path = DEFAULT_OUTPUT,
    split: str = "test",
    limit: int = 0,
    example_ids: set[str] | None = None,
    max_new_tokens: int = 512,
    context_window: int = 2048,
) -> dict[str, Any]:
    examples = load_examples(dataset, split=split, limit=limit)
    if example_ids:
        examples = [example for example in examples if str(example.get("example_id") or "") in example_ids]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    runtime = PeftControllerRuntime(
        adapter=Path(adapter),
        base_model=base_model,
        context_window=context_window,
        max_new_tokens=max_new_tokens,
    )

    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for index, example in enumerate(examples, start=1):
        call_started = time.perf_counter()
        try:
            decision = runtime.predict(example["input"])
            error = None
            raw_preview = json.dumps(decision, ensure_ascii=False, separators=(",", ":"))
        except Exception as exc:
            decision = None
            error = f"{type(exc).__name__}: {exc}"
            raw_preview = ""
        result = {
            "example_id": example.get("example_id"),
            "output": decision,
            "candidate_meta": {
                "model": base_model,
                "adapter": str(adapter),
                "split": split,
                "sequence": index,
                "latency_ms": round((time.perf_counter() - call_started) * 1000, 1),
                "parse_error": error,
                "raw_preview": raw_preview[:1000],
            },
        }
        results.append(result)
        print(f"[{index}/{len(examples)}] {example.get('example_id')} {'ok' if not error else error}", flush=True)

    output.write_text(
        ("\n".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in results) + "\n")
        if results else "",
        encoding="utf-8",
    )
    errors = sum(1 for item in results if (item.get("candidate_meta") or {}).get("parse_error"))
    return {
        "schema_version": "uruk_controller_candidate_run.v1",
        "model": base_model,
        "adapter": str(adapter),
        "split": split,
        "example_count": len(results),
        "parse_error_count": errors,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "predictions_path": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a PEFT adapter as an URUK controller candidate.")
    parser.add_argument("--adapter", default=str(DEFAULT_ADAPTER))
    parser.add_argument("--base-model", default="Qwen/Qwen3-1.7B")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--split", choices=["train", "validation", "test"], default="test")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--example-ids", default="", help="Comma-separated example IDs to evaluate.")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--context-window", type=int, default=2048)
    args = parser.parse_args()
    report = run_peft_candidate(
        adapter=Path(args.adapter),
        base_model=args.base_model,
        dataset=Path(args.dataset),
        output=Path(args.output),
        split=args.split,
        limit=max(0, args.limit),
        example_ids={item.strip() for item in args.example_ids.split(",") if item.strip()} or None,
        max_new_tokens=args.max_new_tokens,
        context_window=args.context_window,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["parse_error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
