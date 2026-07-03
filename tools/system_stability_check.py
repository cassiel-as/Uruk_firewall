"""One-command stability harness for URUK Trinity Console.

This gate intentionally favors deterministic checks.  It should be safe to run
before and after self-upgrade work without spending model calls.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.stability_golden import run_golden_cases  # noqa: E402
from training.benchmark_controller import run_benchmark as run_controller_benchmark  # noqa: E402
from tools.benchmark_runner import run_cases as run_coordinate_benchmark  # noqa: E402


DEFAULT_PYTEST_TARGETS = [
    "tests/test_stability_golden.py",
    "tests/test_app_protocol_compact.py",
    "tests/test_world_simulator.py",
    "tests/test_world_forecast.py",
    "tests/test_world_geotimeline.py",
    "tests/test_cost_aware_router.py",
    "tests/test_inference_governor.py",
    "tests/test_local_model_router.py",
    "tests/test_controller_policy.py",
    "tests/test_controller_training.py",
        "tests/test_controller_candidate.py",
        "tests/test_controller_shadow.py",
        "tests/test_guard_controller_predictions.py",
        "tests/test_controller_learning.py",
    "tests/test_controller_data_factory.py",
    "tests/test_controller_hard_negative_factory.py",
    "tests/test_controller_candidate_curator.py",
    "tests/test_kairos_memory.py",
    "tests/test_knowledge_manifest.py",
    "tests/test_prompt_regression.py",
    "tests/test_runtime_supervisor.py",
    "tests/test_runtime_identity.py",
    "tests/test_failover.py",
    "tests/test_provider_rate_limiter.py",
    "tests/test_protocol_output_guard.py",
    "tests/test_upgrade_engine.py",
    "tests/test_upgrade_report.py",
    "tests/test_upgrade_snapshot.py",
    # ── gate-coverage triage：以下為 deterministic、無 live model / 無 UI 嘅 test ──
    "tests/test_civilizational_clock_canonical.py",
    "tests/test_coordinate_index.py",
    "tests/test_coordinate_knowledge.py",
    "tests/test_council_summary_extractor.py",
    "tests/test_density_audit.py",
    "tests/test_episode_compare.py",
    "tests/test_file_service.py",
    "tests/test_harness_episode.py",
    "tests/test_otel_setup.py",
    "tests/test_pre_gate.py",
    "tests/test_protocol_concepts.py",
    "tests/test_rag_retriever.py",
    "tests/test_relay_protocol.py",
    "tests/test_runtime_summary_indexes.py",
    "tests/test_small_task_executor.py",
    "tests/test_smart_router.py",
    "tests/test_trinity_spirit_modes.py",
    "tests/test_vessel_scanner.py",
    "tests/test_vessel_state.py",
    "tests/test_benchmark_runner.py",
    "tests/test_encoding_audit.py",
    "tests/test_eight_laws.py",
    "tests/test_stability_gate_coverage.py",
]


# ── Gate 覆蓋邊界（宣告座標，唔可以靜默甩 test）──────────────────────────
# 收錄準則：每個 tests/test_*.py 必須二擇一 —— 要麼喺 DEFAULT_PYTEST_TARGETS
# （由 gate 跑），要麼喺 KNOWN_EXCLUDED（連理由）。冇第三種「靜靜唔出現」。
# tests/test_stability_gate_coverage.py 會強制呢條規則，令新 test 唔會好似
# 當初 test_knowledge_manifest 咁靜靜甩出 gate 之外。
KNOWN_EXCLUDED: dict[str, str] = {
    "test_app_controller.py": "需要 Windows UI 自動化 (pywinauto)；環境依賴、非可移植，唔適合放入確定性 gate",
}


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...<truncated>"


def _command_check(
    name: str,
    command: List[str],
    *,
    timeout: int,
    required: bool = True,
) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        elapsed = round(time.perf_counter() - start, 3)
        return {
            "name": name,
            "passed": proc.returncode == 0,
            "required": required,
            "status": "passed" if proc.returncode == 0 else "failed",
            "elapsed_seconds": elapsed,
            "command": command,
            "returncode": proc.returncode,
            "stdout": _truncate(proc.stdout),
            "stderr": _truncate(proc.stderr),
        }
    except FileNotFoundError as exc:
        return {
            "name": name,
            "passed": not required,
            "required": required,
            "status": "failed" if required else "skipped",
            "elapsed_seconds": round(time.perf_counter() - start, 3),
            "command": command,
            "error": f"{type(exc).__name__}: {exc}",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "passed": False,
            "required": required,
            "status": "failed",
            "elapsed_seconds": round(time.perf_counter() - start, 3),
            "command": command,
            "error": f"timeout after {timeout}s",
            "stdout": _truncate(exc.stdout or ""),
            "stderr": _truncate(exc.stderr or ""),
        }


def _report_check(name: str, report: Dict[str, Any]) -> Dict[str, Any]:
    case_count = report.get("case_count")
    if case_count is None:
        case_count = report.get("example_count")
    passed_count = report.get("passed_count")
    if passed_count is None and case_count is not None:
        passed_count = case_count - len(report.get("failures") or [])
    failed_count = report.get("failed_count")
    if failed_count is None:
        failed_count = len(report.get("failures") or [])
    return {
        "name": name,
        "passed": bool(report.get("passed")),
        "required": True,
        "status": "passed" if report.get("passed") else "failed",
        "case_count": case_count,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "report": report,
    }


def _http_json(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
        payload = json.loads(text) if text else {}
        return {"status": response.status, "payload": payload}


def _api_health_check(base_url: str, *, required: bool) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    start = time.perf_counter()
    checks: List[Dict[str, Any]] = []
    try:
        runtime = _http_json(f"{base}/api/runtime/status")
        checks.append({"name": "runtime_status_http_200", "passed": runtime["status"] == 200, "actual": runtime["status"]})
        runtime_payload = runtime.get("payload") or {}
        runtime_dependencies = (runtime.get("payload") or {}).get("dependencies") or {}
        ollama = (runtime_dependencies.get("dependencies") or {}).get("ollama") or {}
        checks.append({
            "name": "ollama_local_only",
            "passed": ollama.get("local_only") is True,
            "actual": {
                "local_only": ollama.get("local_only"),
                "listener_addresses": ollama.get("listener_addresses") or [],
                "security_status": ollama.get("security_status"),
            },
        })
        watchdog_path = ROOT / "data" / "runtime" / "watchdog_state.json"
        try:
            watchdog = json.loads(watchdog_path.read_text(encoding="utf-8"))
        except Exception as exc:
            watchdog = {"read_error": f"{type(exc).__name__}: {exc}"}
        watchdog_config = watchdog.get("config") or {}
        recent_restarts = int(watchdog.get("recent_restart_count") or 0)
        max_restarts = int(watchdog_config.get("max_restarts") or 0)
        checks.append({
            "name": "watchdog_v2_contract",
            "passed": (
                watchdog.get("schema_version") == "uruk_runtime_watchdog.v2"
                and watchdog.get("status") == "healthy"
                and watchdog.get("child_pid") == runtime_payload.get("pid")
                and recent_restarts <= max_restarts
                and (watchdog.get("dependencies") or {}).get("secure") is True
            ),
            "actual": {
                "path": str(watchdog_path),
                "schema_version": watchdog.get("schema_version"),
                "status": watchdog.get("status"),
                "child_pid": watchdog.get("child_pid"),
                "runtime_pid": runtime_payload.get("pid"),
                "recent_restart_count": recent_restarts,
                "max_restarts": max_restarts,
                "dependencies_secure": (watchdog.get("dependencies") or {}).get("secure"),
                "read_error": watchdog.get("read_error"),
            },
        })

        trigger_q = urllib.parse.quote("freedom")
        trigger = _http_json(f"{base}/api/world/trigger?query={trigger_q}")
        trigger_payload = trigger.get("payload") or {}
        checks.append({
            "name": "world_trigger_freedom",
            "passed": bool(((trigger_payload.get("trigger") or {}).get("should_trigger"))),
            "actual": trigger_payload,
        })

        state = _http_json(f"{base}/api/world/state?query={trigger_q}")
        world = (state.get("payload") or {}).get("world") or {}
        checks.append({
            "name": "world_state_entities",
            "passed": bool(world.get("entities")),
            "actual": len(world.get("entities") or []),
        })

        passed = all(item["passed"] for item in checks)
        return {
            "name": "api_health",
            "passed": passed,
            "required": required,
            "status": "passed" if passed else "failed",
            "elapsed_seconds": round(time.perf_counter() - start, 3),
            "base_url": base,
            "checks": checks,
        }
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
        return {
            "name": "api_health",
            "passed": not required,
            "required": required,
            "status": "failed" if required else "skipped",
            "elapsed_seconds": round(time.perf_counter() - start, 3),
            "base_url": base,
            "checks": checks,
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_stability_checks(
    *,
    api_url: str = "http://localhost:8080",
    require_api: bool = False,
    skip_pytest: bool = False,
    pytest_targets: Iterable[str] = DEFAULT_PYTEST_TARGETS,
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    compile_targets = [
        "app.py",
        "server_launcher.py",
        "desktop_launcher.py",
        "upgrade_engine.py",
        "failover.py",
        "services/runtime_supervisor.py",
        "services/runtime_dependencies.py",
        "services/inference_governor.py",
        "services/provider_rate_limiter.py",
        "services/protocol_output_guard.py",
        "services/local_model_router.py",
        "services/controller_policy.py",
        "services/controller_shadow.py",
        "services/controller_learning.py",
        "services/small_task_executor.py",
        "services/task_profiles.py",
        "services/stability_golden.py",
        "services/prompt_regression.py",
        "services/upgrade_snapshot.py",
        "services/upgrade_report.py",
        "services/world_simulator.py",
        "services/world_geotimeline.py",
        "services/world_revision_ledger.py",
        "tools/stability_golden_runner.py",
        "tools/prompt_regression_check.py",
        "tools/runtime_watchdog.py",
        "tools/system_stability_check.py",
        "training/dataset_builder.py",
        "training/dataset_validator.py",
        "training/benchmark_controller.py",
        "training/run_controller_candidate.py",
        "training/run_peft_candidate.py",
        "training/peft_controller_runtime.py",
        "training/controller_shadow_server.py",
        "training/guard_controller_predictions.py",
        "training/controller_learning_queue.py",
        "training/controller_data_factory.py",
        "training/controller_hard_negative_factory.py",
        "training/controller_candidate_curator.py",
        "training/preflight.py",
        "training/train_qlora.py",
        "training/export_ollama.py",
    ]
    checks.append(_command_check(
        "python_compile",
        [sys.executable, "-X", "utf8", "-m", "py_compile", *compile_targets],
        timeout=30,
    ))
    checks.append(_command_check("javascript_syntax", ["node", "--check", "static/app.js"], timeout=30))
    checks.append(_command_check("javascript_atlas_syntax", ["node", "--check", "static/world_atlas.js"], timeout=30))
    checks.append(_command_check(
        "encoding_audit",
        [sys.executable, "-X", "utf8", "tools/encoding_audit.py", "--fail-on-issues"],
        timeout=90,
    ))

    try:
        checks.append(_report_check("coordinate_benchmark", run_coordinate_benchmark(root=ROOT)))
    except Exception as exc:
        checks.append({
            "name": "coordinate_benchmark",
            "passed": False,
            "required": True,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        })

    try:
        checks.append(_report_check("stability_golden", run_golden_cases(root=ROOT)))
    except Exception as exc:
        checks.append({
            "name": "stability_golden",
            "passed": False,
            "required": True,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        })

    try:
        checks.append(_report_check("controller_benchmark", run_controller_benchmark()))
    except Exception as exc:
        checks.append({
            "name": "controller_benchmark",
            "passed": False,
            "required": True,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        })

    if skip_pytest:
        checks.append({
            "name": "pytest_core",
            "passed": True,
            "required": False,
            "status": "skipped",
            "reason": "--skip-pytest",
        })
    else:
        checks.append(_command_check(
            "pytest_core",
            [sys.executable, "-X", "utf8", "-m", "pytest", *pytest_targets, "-q"],
            timeout=120,
        ))

    checks.append(_api_health_check(api_url, required=require_api))

    failed_required = [item for item in checks if item.get("required", True) and not item.get("passed")]
    failed_optional = [item for item in checks if not item.get("required", True) and item.get("status") == "failed"]
    return {
        "schema_version": "system_stability_check.v1",
        "root": str(ROOT),
        "passed": not failed_required,
        "check_count": len(checks),
        "failed_required_count": len(failed_required),
        "failed_optional_count": len(failed_optional),
        "checks": checks,
    }


def _print_summary(report: Dict[str, Any]) -> None:
    status = "PASS" if report.get("passed") else "FAIL"
    print(f"URUK system stability {status}: {report['check_count']} checks")
    for check in report.get("checks") or []:
        mark = "skip" if check.get("status") == "skipped" else ("ok" if check.get("passed") else "FAIL")
        detail = ""
        if "passed_count" in check and "case_count" in check:
            detail = f" {check.get('passed_count')}/{check.get('case_count')}"
        elif "elapsed_seconds" in check:
            detail = f" {check.get('elapsed_seconds')}s"
        if check.get("status") == "skipped" and check.get("error"):
            detail += f" ({check.get('error')})"
        print(f"  {mark} {check.get('name')}{detail}")
        if not check.get("passed") and check.get("status") != "skipped":
            if check.get("error"):
                print(f"      error: {check.get('error')}")
            stderr = (check.get("stderr") or "").strip()
            if stderr:
                print("      stderr:")
                for line in stderr.splitlines()[:8]:
                    print(f"        {line}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run URUK system stability checks.")
    parser.add_argument("--api-url", default="http://localhost:8080", help="Local API base URL for optional health checks.")
    parser.add_argument("--require-api", action="store_true", help="Fail if the local API is not reachable.")
    parser.add_argument("--skip-pytest", action="store_true", help="Skip the pytest stability subset.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    parser.add_argument("--write-json", default="", help="Optional path to write the full JSON report.")
    args = parser.parse_args()

    report = run_stability_checks(
        api_url=args.api_url,
        require_api=args.require_api,
        skip_pytest=args.skip_pytest,
    )

    if args.write_json:
        out = Path(args.write_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_summary(report)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
