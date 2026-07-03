import json
from pathlib import Path

from services.stability_golden import DEFAULT_CASES, run_golden_cases


def test_stability_golden_manifest_has_unique_case_ids():
    payload = json.loads(Path(DEFAULT_CASES).read_text(encoding="utf-8"))
    case_ids = [case["id"] for case in payload["cases"]]

    assert payload["schema_version"] == "stability_golden.v1"
    assert len(case_ids) == len(set(case_ids))
    assert {"route", "kairos_memory", "world_trigger", "world_simulation", "runtime_identity"} <= {
        case["type"] for case in payload["cases"]
    }


def test_stability_golden_cases_pass_against_current_runtime_contracts():
    report = run_golden_cases()

    failed = [item for item in report["results"] if not item["passed"]]
    assert report["passed"] is True, failed
    assert report["passed_count"] == report["case_count"]
