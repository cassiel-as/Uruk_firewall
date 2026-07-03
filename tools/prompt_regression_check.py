"""CLI for URUK prompt regression checks."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.prompt_regression import (  # noqa: E402
    DEFAULT_BASELINE_PATH,
    run_prompt_regression_check,
)


def _print_summary(report: dict) -> None:
    diff = report.get("diff") or {}
    checks = report.get("checks") or {}
    benchmark = checks.get("benchmark") or {}
    quick_eval = checks.get("quick_eval") or {}
    episode = checks.get("episode_compare") or {}
    fingerprint = report.get("fingerprint") or {}
    print(f"URUK prompt regression: {report.get('status')} ok={report.get('ok')}")
    print(f"  prompt_hash: {str(fingerprint.get('sha256') or '')[:12]} files={fingerprint.get('file_count')}")
    print(f"  baseline: {'present' if report.get('baseline_present') else 'missing'}")
    if diff.get("prompt_changed"):
        print(
            "  prompt_changed: "
            f"added={len(diff.get('added') or [])} "
            f"removed={len(diff.get('removed') or [])} "
            f"changed={len(diff.get('changed') or [])}"
        )
    else:
        print("  prompt_changed: no")
    if benchmark:
        print(f"  benchmark: {benchmark.get('passed_count', 0)}/{benchmark.get('case_count', 0)} passed")
    if quick_eval:
        q = "PASS" if quick_eval.get("passed") is True else ("FAIL" if quick_eval.get("passed") is False else "SKIP")
        print(f"  quick_eval: {q} {quick_eval.get('reason') or ''}".rstrip())
    if episode:
        print(f"  episode_compare: {episode.get('status')} ok={episode.get('ok')}")
    if report.get("failures"):
        print("  failures: " + ", ".join(report["failures"]))
    if report.get("warnings"):
        print("  warnings: " + ", ".join(report["warnings"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic URUK prompt regression checks.")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE_PATH), help="Prompt regression baseline JSON path.")
    parser.add_argument("--update-baseline", action="store_true", help="Write current prompt fingerprint as baseline.")
    parser.add_argument("--label", default="manual", help="Baseline label when --update-baseline is used.")
    parser.add_argument("--no-benchmark", action="store_true", help="Skip coordinate benchmark.")
    parser.add_argument("--no-quick-eval", action="store_true", help="Skip external quick_eval gate.")
    parser.add_argument("--episode-latest", action="store_true", help="Include latest episode comparison.")
    parser.add_argument("--strict-episode", action="store_true", help="Treat episode regressions as failures.")
    parser.add_argument("--fail-on-change", action="store_true", help="Exit non-zero when prompt bundle changed.")
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    parser.add_argument("--root", default=str(ROOT), help="Repository root.")
    args = parser.parse_args()

    report = run_prompt_regression_check(
        root=Path(args.root),
        baseline_path=Path(args.baseline),
        update_baseline=args.update_baseline,
        run_benchmark=not args.no_benchmark,
        run_quick_eval=not args.no_quick_eval,
        compare_latest_episode=args.episode_latest,
        strict_episode=args.strict_episode,
        label=args.label,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_summary(report)

    fail_on_change = args.fail_on_change and (report.get("diff") or {}).get("prompt_changed")
    return 1 if (not report.get("ok") or fail_on_change) else 0


if __name__ == "__main__":
    raise SystemExit(main())
