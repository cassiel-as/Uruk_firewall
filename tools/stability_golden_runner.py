"""Run URUK deterministic stability golden cases."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.stability_golden import DEFAULT_CASES, run_golden_cases  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic URUK runtime stability golden cases.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="Path to stability_golden_cases.json")
    parser.add_argument("--json", action="store_true", help="Emit full JSON report")
    args = parser.parse_args()

    report = run_golden_cases(Path(args.cases), root=ROOT)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if report["passed"] else "FAIL"
        print(f"URUK stability golden {status}: {report['passed_count']}/{report['case_count']} passed")
        for item in report["results"]:
            mark = "ok" if item.get("passed") else "FAIL"
            failed = [c for c in item.get("checks", []) if not c.get("passed")]
            suffix = "" if not failed else " :: " + "; ".join(f"{c.get('name')} actual={c.get('actual')!r}" for c in failed)
            print(f"  {mark} {item.get('id')} [{item.get('type')}]{suffix}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
