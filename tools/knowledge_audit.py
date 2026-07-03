"""
CLI wrapper for the URUK knowledge manifest audit.

Examples:
    py -m tools.knowledge_audit --summary
    py -m tools.knowledge_audit --json
    py -m tools.knowledge_audit --summary --strict
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from services.knowledge_manifest import ROOT, audit_knowledge


def _safe_print(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    safe = str(text).encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")
    print(safe)


def _print_summary(report: dict) -> None:
    summary = report["summary"]
    rag = report["rag"]
    cau = report.get("cau_structure") or {}
    issues = report["issues"]
    counts = summary["issues"]
    _safe_print("URUK knowledge audit")
    _safe_print(f"  documents: {summary['documents']} active={summary['active']} canonical={summary['canonical']}")
    _safe_print(
        "  issues: "
        f"P0={counts['P0']} P1={counts['P1']} P2={counts['P2']} P3={counts['P3']}"
    )
    _safe_print(
        "  rag: "
        f"present={rag['present']} chunks={rag.get('n_chunks')} built_at={rag.get('built_at')}"
    )
    if cau:
        _safe_print(
            "  cau_structure: "
            f"checked={cau.get('checked')} passed={cau.get('passed')} failed={cau.get('failed')}"
        )
    if not issues:
        _safe_print("  status: clean")
        return
    _safe_print("  findings:")
    for issue in issues:
        loc = f" [{issue.get('path')}]" if issue.get("path") else ""
        _safe_print(f"    - {issue['severity']} {issue['code']}{loc}: {issue['message']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit URUK knowledge manifest health.")
    parser.add_argument("--root", default=str(ROOT), help="Repository root path.")
    parser.add_argument("--manifest", default=None, help="Override knowledge_manifest.json path.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    parser.add_argument("--summary", action="store_true", help="Print compact human summary.")
    parser.add_argument("--include-documents", action="store_true", help="Include document inventory in JSON output.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on P0 issues.")
    args = parser.parse_args(argv)

    root = Path(args.root)
    manifest_path = Path(args.manifest) if args.manifest else None
    report = audit_knowledge(
        root=root,
        manifest_path=manifest_path,
        include_documents=args.include_documents,
    )

    if args.json:
        _safe_print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        _print_summary(report)

    if args.strict and report["summary"]["fatal"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
