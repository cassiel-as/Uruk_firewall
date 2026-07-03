"""CLI for generating URUK self-upgrade reports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.upgrade_report import generate_self_upgrade_report, list_reports  # noqa: E402


def _print_summary(report: dict) -> None:
    summary = report.get("summary") or {}
    files = report.get("files") or {}
    print(f"URUK self-upgrade report: {report.get('status')} ok={report.get('ok')}")
    print(f"  report_id: {report.get('report_id')}")
    print(f"  latest_plan: {summary.get('latest_plan_id') or '--'} {summary.get('latest_plan_status') or ''}".rstrip())
    print(f"  gates_ok: {summary.get('gates_ok')}")
    print(f"  prompt_regression: {summary.get('prompt_regression_status')}")
    print(f"  action_items: {summary.get('action_count')}")
    if files:
        print(f"  markdown: {files.get('markdown_path') or '--'}")
        print(f"  json: {files.get('json_path') or '--'}")


def _print_reports(root: Path, limit: int) -> None:
    reports = list_reports(root=root, limit=limit)
    if not reports:
        print("No self-upgrade reports found.")
        return
    for item in reports:
        summary = item.get("summary") or {}
        print(
            f"{item.get('report_id')} · {item.get('status')} · "
            f"latest={summary.get('latest_plan_id') or '--'} · "
            f"actions={summary.get('action_count')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or list URUK self-upgrade reports.")
    parser.add_argument("--root", default=str(ROOT), help="Repository root.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown report.")
    parser.add_argument("--no-write", action="store_true", help="Do not write report artifacts.")
    parser.add_argument("--no-gates", action="store_true", help="Skip deterministic upgrade gate preflight.")
    parser.add_argument("--no-prompt-regression", action="store_true", help="Skip prompt regression checks.")
    parser.add_argument("--plan-limit", type=int, default=8, help="Number of recent plans to include.")
    parser.add_argument("--log-limit", type=int, default=12, help="Number of upgrade log entries to include.")
    parser.add_argument("--list", action="store_true", help="List existing reports instead of generating one.")
    parser.add_argument("--fail-on-blocked", action="store_true", help="Exit non-zero when the generated report status is blocked.")
    args = parser.parse_args()

    root = Path(args.root)
    if args.list:
        _print_reports(root, args.plan_limit)
        return 0

    report = generate_self_upgrade_report(
        root=root,
        plan_limit=args.plan_limit,
        log_limit=args.log_limit,
        run_gates=not args.no_gates,
        run_prompt_regression=not args.no_prompt_regression,
        write=not args.no_write,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.markdown:
        print(report.get("markdown") or "")
    else:
        _print_summary(report)
    return 1 if args.fail_on_blocked and not report.get("ok") else 0


if __name__ == "__main__":
    raise SystemExit(main())
