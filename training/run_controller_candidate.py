"""Run an Ollama model as an URUK controller candidate and write predictions."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.dataset_validator import dataset_paths, iter_jsonl  # noqa: E402


DEFAULT_DATASET_DIR = ROOT / "training" / "generated"
DEFAULT_OUTPUT = ROOT / "training" / "predictions" / "ollama_controller_test.jsonl"
SYSTEM_PROMPT = (ROOT / "training" / "controller_system_prompt.txt").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "training" / "controller_schema.json").read_text(encoding="utf-8"))
DECISION_SCHEMA = SCHEMA["$defs"]["controllerDecision"]


def parse_decision(text: str) -> tuple[dict[str, Any], str | None]:
    raw = str(text or "").strip()
    if not raw:
        return {}, "empty_response"
    try:
        value = json.loads(raw)
        return (value, None) if isinstance(value, dict) else ({}, "response_not_object")
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {}, "json_object_not_found"
        try:
            value = json.loads(match.group(0))
            return (value, None) if isinstance(value, dict) else ({}, "response_not_object")
        except json.JSONDecodeError as exc:
            return {}, f"json_decode_error: {exc}"


def load_examples(dataset: Path, *, split: str = "test", limit: int = 0) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for path in dataset_paths(Path(dataset)):
        for _, value in iter_jsonl(path):
            if not isinstance(value, dict) or "_json_error" in value:
                continue
            if split and value.get("split") != split:
                continue
            examples.append(value)
            if limit and len(examples) >= limit:
                return examples
    return examples


def run_ollama_candidate(
    *,
    model: str,
    dataset: Path = DEFAULT_DATASET_DIR,
    output: Path = DEFAULT_OUTPUT,
    split: str = "test",
    limit: int = 0,
    api_base: str = "http://localhost:11434",
    timeout: float = 45.0,
    context_window: int = 4096,
    keep_alive: str = "30m",
) -> dict[str, Any]:
    examples = load_examples(dataset, split=split, limit=limit)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    started = time.perf_counter()

    with httpx.Client(timeout=timeout) as client:
        for index, example in enumerate(examples, start=1):
            call_started = time.perf_counter()
            error: str | None = None
            raw = ""
            decision: dict[str, Any] = {}
            try:
                response = client.post(
                    f"{api_base.rstrip('/')}/api/generate",
                    json={
                        "model": model,
                        "system": SYSTEM_PROMPT,
                        "prompt": json.dumps(example["input"], ensure_ascii=False, separators=(",", ":")),
                        "stream": False,
                        "think": False,
                        "keep_alive": keep_alive,
                        "format": DECISION_SCHEMA,
                        "options": {
                            "temperature": 0,
                            "num_ctx": int(context_window),
                            "num_predict": 512,
                        },
                    },
                )
                response.raise_for_status()
                payload = response.json()
                raw = str(payload.get("response") or "")
                decision, error = parse_decision(raw)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            result = {
                "example_id": example.get("example_id"),
                "output": decision,
                "candidate_meta": {
                    "model": model,
                    "split": split,
                    "sequence": index,
                    "latency_ms": round((time.perf_counter() - call_started) * 1000, 1),
                    "parse_error": error,
                    "raw_preview": raw[:1000],
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
        "model": model,
        "split": split,
        "example_count": len(results),
        "parse_error_count": errors,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "predictions_path": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an Ollama model as an URUK controller candidate.")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--split", choices=["train", "validation", "test"], default="test")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--api-base", default="http://localhost:11434")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--context-window", type=int, default=4096)
    parser.add_argument("--keep-alive", default="30m")
    args = parser.parse_args()
    report = run_ollama_candidate(
        model=args.model,
        dataset=Path(args.dataset),
        output=Path(args.output),
        split=args.split,
        limit=max(0, args.limit),
        api_base=args.api_base,
        timeout=args.timeout,
        context_window=args.context_window,
        keep_alive=args.keep_alive,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["parse_error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
