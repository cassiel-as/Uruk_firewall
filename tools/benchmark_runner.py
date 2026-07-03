"""Deterministic benchmark runner for URUK coordinate foundation cases."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.coordinate_knowledge import (  # noqa: E402
    evaluate_coordinate_output,
    select_coordinate_cards,
)
from services.cost_aware_router import route_query  # noqa: E402

DEFAULT_CASES = ROOT / "data" / "benchmarks" / "benchmark_cases.json"


def _contains(text: str, term: str) -> bool:
    return str(term or "").casefold() in str(text or "").casefold()


def _subset(expected: Iterable[str], actual: Iterable[str]) -> bool:
    return set(expected or []).issubset(set(actual or []))


def run_cases(cases_path: Path = DEFAULT_CASES, *, root: Path = ROOT) -> Dict[str, Any]:
    payload = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    results: List[Dict[str, Any]] = []

    for case in payload.get("cases", []) or []:
        case_id = case.get("id")
        query = case.get("input", "")
        answer = case.get("sample_good_answer", "")
        selected = select_coordinate_cards(query, root=root)
        selected_ids = [card.get("id") for card in selected]
        expected_ids = case.get("expected_cards") or []

        selection_pass = _subset(expected_ids, selected_ids)
        eval_result = evaluate_coordinate_output(query, answer, root=root)
        min_score = case.get("min_score")
        if min_score is None:
            score_pass = True
        else:
            score = eval_result.get("score")
            score_pass = isinstance(score, (int, float)) and score >= float(min_score)

        required_coordinate_use = case.get("required_coordinate_use")
        coordinate_use_pass = (
            True if not required_coordinate_use
            else eval_result.get("coordinate_use") == required_coordinate_use
        )

        flags = case.get("required_flags") or {}
        flag_failures = {
            key: {"expected": value, "actual": eval_result.get(key)}
            for key, value in flags.items()
            if eval_result.get(key) != value
        }

        forbidden = case.get("forbidden_terms") or []
        forbidden_hits = [term for term in forbidden if _contains(answer, term)]
        route = route_query(query, root=root)
        cost_metrics = route.get("cost_metrics") or {}

        passed = (
            selection_pass
            and score_pass
            and coordinate_use_pass
            and not flag_failures
            and not forbidden_hits
        )
        results.append({
            "id": case_id,
            "passed": passed,
            "selection_pass": selection_pass,
            "expected_cards": expected_ids,
            "selected_cards": selected_ids,
            "score_pass": score_pass,
            "score": eval_result.get("score"),
            "coordinate_use": eval_result.get("coordinate_use"),
            "coordinate_use_pass": coordinate_use_pass,
            "flag_failures": flag_failures,
            "forbidden_hits": forbidden_hits,
            "route_kind": route.get("route_kind"),
            "model_tier": route.get("model_tier"),
            "cost_metrics": cost_metrics,
        })

    failed = [item for item in results if not item["passed"]]
    total_model_calls = sum(int(((item.get("cost_metrics") or {}).get("estimated_model_calls") or 0)) for item in results)
    total_api_calls = sum(int(((item.get("cost_metrics") or {}).get("estimated_api_model_calls") or 0)) for item in results)
    total_context_tokens = sum(int(((item.get("cost_metrics") or {}).get("estimated_context_tokens") or 0)) for item in results)
    return {
        "suite_id": payload.get("suite_id"),
        "case_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_count": len(failed),
        "passed": not failed,
        "cost_summary": {
            "estimated_model_calls": total_model_calls,
            "estimated_api_model_calls": total_api_calls,
            "estimated_context_tokens": total_context_tokens,
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic URUK benchmark cases.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="Path to benchmark_cases.json")
    parser.add_argument("--json", action="store_true", help="Emit full JSON report")
    args = parser.parse_args()

    report = run_cases(Path(args.cases))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if report["passed"] else "FAIL"
        print(f"URUK benchmark {status}: {report['passed_count']}/{report['case_count']} passed")
        for item in report["results"]:
            mark = "ok" if item["passed"] else "FAIL"
            print(f"  {mark} {item['id']} score={item['score']} selected={','.join(item['selected_cards'])}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
