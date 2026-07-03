"""CLI wrapper for URUK content encoding audit."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.encoding_audit import audit_encoding, format_summary, to_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan text files for encoding corruption and mojibake markers.")
    parser.add_argument("--root", default=str(ROOT), help="Repository root.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit non-zero when any file is flagged.")
    args = parser.parse_args()

    report = audit_encoding(root=Path(args.root))
    print(to_json(report) if args.json else format_summary(report))
    return 1 if args.fail_on_issues and not report.get("clean") else 0


if __name__ == "__main__":
    raise SystemExit(main())
