"""CLI for deterministic URUK harness episode comparison."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.episode_compare import (  # noqa: E402
    compare_episodes,
    compare_latest,
    list_episode_paths,
)


def _print_summary(report: dict) -> None:
    left = report.get("left") or {}
    right = report.get("right") or {}
    metrics = report.get("metrics") or {}
    coord = metrics.get("coordinate_score") or {}
    missing = metrics.get("coordinate_missing_count") or {}
    trace = metrics.get("knowledge_trace_count") or {}
    print(f"URUK episode compare: {report.get('status')} ok={report.get('ok')}")
    print(f"  left : {left.get('episode_id')} [{left.get('pipeline_mode')}]")
    print(f"  right: {right.get('episode_id')} [{right.get('pipeline_mode')}]")
    print(f"  coordinate_score delta: {coord.get('delta')}")
    print(f"  coordinate_missing delta: {missing.get('delta')}")
    print(f"  trace_count delta: {trace.get('delta')}")
    if report.get("regressions"):
        print("  regressions: " + ", ".join(report["regressions"]))
    if report.get("improvements"):
        print("  improvements: " + ", ".join(report["improvements"]))
    if report.get("changes"):
        print("  changes: " + ", ".join(report["changes"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare URUK harness episode JSON files.")
    parser.add_argument("left", nargs="?", help="Baseline/older episode id or path.")
    parser.add_argument("right", nargs="?", help="Candidate/newer episode id or path.")
    parser.add_argument("--latest", action="store_true", help="Compare the two newest episodes.")
    parser.add_argument("--list", type=int, default=0, help="List latest N episodes and exit.")
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when regressions are detected.")
    parser.add_argument("--root", default=str(ROOT), help="Repository root.")
    args = parser.parse_args()

    root = Path(args.root)
    if args.list:
        for path in list_episode_paths(root=root, limit=args.list):
            print(path)
        return 0

    if args.latest or (not args.left and not args.right):
        report = compare_latest(root=root)
    else:
        if not args.left or not args.right:
            parser.error("provide both left and right, or use --latest")
        report = compare_episodes(args.left, args.right, root=root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_summary(report)
    return 1 if args.strict and report.get("regressions") else 0


if __name__ == "__main__":
    raise SystemExit(main())
