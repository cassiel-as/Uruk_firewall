import sys
import tempfile
import unittest
from pathlib import Path

import upgrade_engine
from services import computer_tools


class UpgradeEngineContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.custom_dir = Path(self.tmp.name) / "custom_tools"
        self.data_dir = Path(self.tmp.name) / "data"
        self.orig_upgrade_custom_dir = upgrade_engine.CUSTOM_DIR
        self.orig_upgrade_data_dir = upgrade_engine.DATA_DIR
        self.orig_upgrade_plans_dir = upgrade_engine.PLANS_DIR
        self.orig_upgrade_log_path = upgrade_engine.LOG_PATH
        self.orig_upgrade_baselines_path = upgrade_engine.BASELINES_PATH
        self.orig_tools_custom_dir = computer_tools._CUSTOM_TOOLS_DIR
        self.orig_registry = dict(computer_tools.TOOL_REGISTRY)
        self.orig_dispatch = dict(computer_tools._CUSTOM_DISPATCH)
        upgrade_engine.CUSTOM_DIR = self.custom_dir
        upgrade_engine.DATA_DIR = self.data_dir
        upgrade_engine.PLANS_DIR = self.data_dir / "upgrade_plans"
        upgrade_engine.LOG_PATH = self.data_dir / "upgrade_log.jsonl"
        upgrade_engine.BASELINES_PATH = self.data_dir / "upgrade_baselines.json"
        computer_tools._CUSTOM_TOOLS_DIR = self.custom_dir

    def tearDown(self):
        upgrade_engine.CUSTOM_DIR = self.orig_upgrade_custom_dir
        upgrade_engine.DATA_DIR = self.orig_upgrade_data_dir
        upgrade_engine.PLANS_DIR = self.orig_upgrade_plans_dir
        upgrade_engine.LOG_PATH = self.orig_upgrade_log_path
        upgrade_engine.BASELINES_PATH = self.orig_upgrade_baselines_path
        computer_tools._CUSTOM_TOOLS_DIR = self.orig_tools_custom_dir
        computer_tools.TOOL_REGISTRY.clear()
        computer_tools.TOOL_REGISTRY.update(self.orig_registry)
        computer_tools._CUSTOM_DISPATCH.clear()
        computer_tools._CUSTOM_DISPATCH.update(self.orig_dispatch)
        for name in list(sys.modules):
            if name.startswith("services.custom_tools.zz_unit_"):
                sys.modules.pop(name, None)
        self.tmp.cleanup()

    def test_parse_tool_spec_keeps_tool_and_arg_descriptions_separate(self):
        response = """[TOOL_SPEC:upgrade-unit]
name: zz_unit_parse_probe
description: top-level tool description
category: misc
args:
  - name: path
    type: str
    required: false
    description: argument description only
python_code: |
  def execute(args: dict) -> dict:
      return {"ok": True, "path": args.get("path")}
---"""

        specs = upgrade_engine.parse_claude_response("upgrade-unit", response)

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["description"], "top-level tool description")
        self.assertEqual(specs[0]["args"][0]["description"], "argument description only")
        self.assertFalse(specs[0]["args"][0]["required"])

    def test_validate_rejects_missing_dependency(self):
        spec = {
            "name": "zz_unit_missing_dep",
            "description": "missing dependency probe",
            "category": "misc",
            "args": [],
            "python_code": (
                "import definitely_missing_uruk_dependency\n\n"
                "def execute(args: dict) -> dict:\n"
                "    return {\"ok\": True}\n"
            ),
        }

        result = upgrade_engine.step_validate_tool_specs([spec])

        self.assertEqual(result["pass_count"], 0)
        self.assertEqual(result["fail_count"], 1)
        self.assertIn("definitely_missing_uruk_dependency", result["failed"][0]["reasons"][0])

    def test_validation_failure_summary_omits_generated_code(self):
        failures = [{
            "spec": {
                "name": "zz_unit_missing_dep",
                "python_code": "def execute(args: dict) -> dict:\n    return {'ok': True}",
            },
            "reasons": ["缺少依賴: import definitely_missing_uruk_dependency"],
        }]

        summary = upgrade_engine._summarize_validation_failures(failures)

        self.assertIn("zz_unit_missing_dep", summary)
        self.assertIn("缺少依賴", summary)
        self.assertNotIn("python_code", summary)
        self.assertNotIn("def execute", summary)

    def test_validate_routes_high_risk_tool_to_human_review(self):
        spec = {
            "name": "zz_unit_review_probe",
            "description": "review probe",
            "category": "file",
            "args": [],
            "python_code": (
                "def execute(args: dict) -> dict:\n"
                "    with open('probe.txt', 'w', encoding='utf-8') as handle:\n"
                "        handle.write('x')\n"
                "    return {\"ok\": True}\n"
            ),
        }

        result = upgrade_engine.step_validate_tool_specs([spec])

        self.assertEqual(result["pass_count"], 0)
        self.assertEqual(result["fail_count"], 0)
        self.assertEqual(result["review_count"], 1)
        self.assertIn("open()", " ".join(result["needs_review"][0]["reasons"]))

    def test_install_hot_reload_and_smoke_test_safe_tool(self):
        spec = {
            "name": "zz_unit_safe_tool",
            "description": "safe smoke test probe",
            "category": "misc",
            "args": [{"name": "value", "type": "str", "required": True, "description": "value"}],
            "python_code": (
                "def execute(args: dict) -> dict:\n"
                "    return {\"ok\": True, \"value\": args.get(\"value\")}\n"
            ),
        }

        validation = upgrade_engine.step_validate_tool_specs([spec])
        self.assertEqual(validation["pass_count"], 1)

        installed = upgrade_engine.step_install_tools(validation["passed"])
        self.assertEqual(installed, ["zz_unit_safe_tool"])

        reload_result = upgrade_engine.step_hot_reload()
        self.assertIn("zz_unit_safe_tool", reload_result["reloaded"])
        self.assertIn("zz_unit_safe_tool", computer_tools.TOOL_REGISTRY)

        smoke = upgrade_engine.step_smoke_test(["zz_unit_safe_tool"])
        self.assertEqual(smoke["passed"], ["zz_unit_safe_tool"])
        self.assertEqual(smoke["failed"], [])

    def test_pre_install_snapshot_records_manifest_on_plan(self):
        plan = upgrade_engine.UpgradePlan(
            plan_id="upgrade-unit-snapshot",
            mode="audit",
            relay_target="unit",
            created_at="2026-06-01T00:00:00",
            status="installing",
            summary="snapshot probe.",
        )

        snapshot = upgrade_engine.step_pre_install_snapshot(plan)

        self.assertIn("pre_install", plan.snapshots)
        self.assertTrue(Path(snapshot["path"]).exists())
        self.assertEqual(snapshot["file_count"], plan.snapshots["pre_install"]["file_count"])
        self.assertEqual(len(snapshot["aggregate_sha256"]), 64)

    def test_rollback_includes_snapshot_diff_when_available(self):
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        existing = self.custom_dir / "zz_unit_existing.py"
        existing.write_text("VALUE = 'before'\n", encoding="utf-8")
        plan = upgrade_engine.UpgradePlan(
            plan_id="upgrade-unit-rollback-diff",
            mode="audit",
            relay_target="unit",
            created_at="2026-06-01T00:00:00",
            status="installing",
            summary="rollback diff probe.",
        )
        upgrade_engine.step_pre_install_snapshot(plan)
        existing.write_text("VALUE = 'after'\n", encoding="utf-8")

        rollback = upgrade_engine.step_rollback(plan, [])

        self.assertIn("snapshot_diff", rollback)
        self.assertGreaterEqual(rollback["snapshot_diff"]["changed_count"], 1)
        self.assertTrue(any("zz_unit_existing.py" in p for p in rollback["snapshot_diff"]["changed"]))

    def test_scan_sessions_reads_harness_episode_trace_and_validators(self):
        episode_dir = self.data_dir / "harness_episodes" / "2026-05-30"
        episode_dir.mkdir(parents=True)
        (episode_dir / "trinity_probe.json").write_text(
            """{
              "episode_id": "trinity_probe",
              "run": {"input": "read an Excel file", "pipeline_mode": "auto"},
              "context": {
                "knowledge": {
                  "health": {"clean": false, "summary": {"issues": {"P0": 1}}},
                  "trace": [{"source": "manual_ref"}]
                }
              },
              "validators": {
                "output_density_audit": {"audit_ran": false, "density": "LOW", "errors": ["audit missing"]},
                "council_decision": {"verdict": "consensus"},
                "coordinate_output_eval": {"active": true, "target": "system_output", "score": 0.5, "missing_count": 1},
                "father_paused": false
              }
            }""",
            encoding="utf-8",
        )

        result = upgrade_engine.step_scan_sessions(max_n=5)

        self.assertEqual(result["source"], "harness_episodes")
        self.assertEqual(result["analyzed"], 1)
        self.assertEqual(result["errors_found"], 3)
        self.assertEqual(result["snippets"][0]["episode_id"], "trinity_probe")
        self.assertEqual(result["snippets"][0]["knowledge_trace_count"], 1)
        self.assertTrue(result["snippets"][0]["coordinate_output_eval_active"])
        self.assertEqual(result["snippets"][0]["coordinate_output_eval_score"], 0.5)
        self.assertEqual(result["snippets"][0]["coordinate_output_eval_missing_count"], 1)
        self.assertTrue(result["snippets"][0]["coordinate_eval_active"])
        self.assertEqual(result["snippets"][0]["coordinate_eval_score"], 0.5)
        self.assertEqual(result["snippets"][0]["coordinate_eval_missing_count"], 1)
        self.assertFalse(result["snippets"][0]["knowledge_clean"])

    def test_identify_gaps_includes_vessel_hardware_gaps(self):
        tool_scan = {
            "count": 2,
            "tools": ["capture_screenshot", "ocr_read_screen"],
            "by_category": {"screen": ["capture_screenshot", "ocr_read_screen"]},
        }
        session_scan = {"error_samples": []}
        log_scan = {"installed_tools": []}
        vessel_scan = {
            "vessel_id": "unit-vessel",
            "capabilities": ["compute.local_cpu", "bus.serial", "actuator.motor_control_candidate"],
            "devices": [{"kind": "serial", "name": "COM7", "path": "COM7"}],
        }

        gaps = upgrade_engine.step_identify_gaps(
            tool_scan,
            session_scan,
            log_scan,
            perf_gaps=[],
            vessel_scan=vessel_scan,
        )

        hardware = [g for g in gaps if g.get("type") == "hardware_gap"]
        self.assertTrue(hardware)
        self.assertEqual(hardware[0]["hardware_capability"], "bus.serial")
        self.assertEqual(hardware[0]["suggested_name"], "move_servo")

    def test_builtin_benchmark_gate_passes_coordinate_suite(self):
        result = upgrade_engine.benchmark_gate()

        self.assertTrue(result["passed"], result)
        self.assertGreaterEqual(result["case_count"], 10)
        self.assertEqual(result["failed_count"], 0)

    def test_stability_golden_gate_passes_runtime_contracts(self):
        result = upgrade_engine.stability_golden_gate()

        self.assertTrue(result["passed"], result)
        self.assertGreaterEqual(result["case_count"], 10)
        self.assertEqual(result["failed_count"], 0)

    def test_upgrade_gate_preflight_is_read_only_and_reports_gates(self):
        result = upgrade_engine.run_upgrade_gate_preflight()

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["knowledge_audit"]["passed"], result)
        self.assertTrue(result["benchmark"]["passed"], result)
        self.assertTrue(result["stability_golden"]["passed"], result)
        self.assertIn("quick_eval", result)
        self.assertIn("checked_at", result)

    def test_build_plan_labels_chatgpt_as_relay_wait(self):
        original_scan_tools = upgrade_engine.step_scan_tools
        original_scan_vessel = upgrade_engine.step_scan_vessel
        original_scan_sessions = upgrade_engine.step_scan_sessions
        original_scan_log = upgrade_engine.step_scan_upgrade_log
        original_perf_scan = upgrade_engine.performance_gap_scan
        original_identify = upgrade_engine.step_identify_gaps
        original_self_audit = upgrade_engine.run_upgrade_self_audit
        try:
            upgrade_engine.step_scan_tools = lambda: {"count": 1, "tool_names": ["unit_tool"], "categories": {}}
            upgrade_engine.step_scan_vessel = lambda: {"profile": {}, "hardware_gaps": []}
            upgrade_engine.step_scan_sessions = lambda _max_sessions: {"analyzed": 0, "error_samples": [], "snippets": []}
            upgrade_engine.step_scan_upgrade_log = lambda: {"installed_tools": []}
            upgrade_engine.performance_gap_scan = lambda: []
            upgrade_engine.step_identify_gaps = lambda *_args, **_kwargs: []
            upgrade_engine.run_upgrade_self_audit = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("skip"))

            plan = upgrade_engine.build_plan("audit", relay_target="chatgpt", max_sessions=1)
        finally:
            upgrade_engine.step_scan_tools = original_scan_tools
            upgrade_engine.step_scan_vessel = original_scan_vessel
            upgrade_engine.step_scan_sessions = original_scan_sessions
            upgrade_engine.step_scan_upgrade_log = original_scan_log
            upgrade_engine.performance_gap_scan = original_perf_scan
            upgrade_engine.step_identify_gaps = original_identify
            upgrade_engine.run_upgrade_self_audit = original_self_audit

        self.assertEqual(plan.status, "waiting_relay")
        self.assertIn("等待 ChatGPT Desktop", plan.summary)
        self.assertEqual(plan.get_step("design_tools").executor, "chatgpt")

    def test_post_install_eval_rolls_back_on_failed_builtin_benchmark(self):
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        tool_path = self.custom_dir / "zz_unit_gate_probe.py"
        tool_path.write_text("def execute(args):\n    return {'ok': True}\n", encoding="utf-8")
        plan = upgrade_engine.UpgradePlan(
            plan_id="upgrade-unit-gate",
            mode="audit",
            relay_target="unit",
            created_at="2026-06-01T00:00:00",
            status="installing",
            summary="unit probe.",
        )
        plan.steps = [
            upgrade_engine._make_step(
                10,
                "system",
                "post_install_eval",
                "unit post-install eval",
            )
        ]

        original_knowledge_gate = upgrade_engine.knowledge_audit_gate
        original_benchmark_gate = upgrade_engine.benchmark_gate
        try:
            upgrade_engine.knowledge_audit_gate = lambda: {"passed": True}
            upgrade_engine.benchmark_gate = lambda: {
                "passed": False,
                "case_count": 10,
                "passed_count": 9,
                "failed_count": 1,
                "failed_cases": ["coord-unit-failure"],
            }

            result = upgrade_engine.step_post_install_eval(plan, ["zz_unit_gate_probe"])
        finally:
            upgrade_engine.knowledge_audit_gate = original_knowledge_gate
            upgrade_engine.benchmark_gate = original_benchmark_gate

        self.assertTrue(result["regressed"])
        self.assertEqual(result["reason"], "coordinate_benchmark_failed")
        self.assertEqual(plan.status, "rolled_back")
        self.assertFalse(tool_path.exists())
        self.assertEqual(result["rollback"]["removed"], ["zz_unit_gate_probe"])

    def test_post_install_eval_rolls_back_on_failed_stability_golden(self):
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        tool_path = self.custom_dir / "zz_unit_stability_probe.py"
        tool_path.write_text("def execute(args):\n    return {'ok': True}\n", encoding="utf-8")
        plan = upgrade_engine.UpgradePlan(
            plan_id="upgrade-unit-stability",
            mode="audit",
            relay_target="unit",
            created_at="2026-06-01T00:00:00",
            status="installing",
            summary="unit stability probe.",
        )
        plan.steps = [
            upgrade_engine._make_step(
                10,
                "system",
                "post_install_eval",
                "unit post-install eval",
            )
        ]

        original_knowledge_gate = upgrade_engine.knowledge_audit_gate
        original_benchmark_gate = upgrade_engine.benchmark_gate
        original_stability_gate = upgrade_engine.stability_golden_gate
        try:
            upgrade_engine.knowledge_audit_gate = lambda: {"passed": True}
            upgrade_engine.benchmark_gate = lambda: {"passed": True, "case_count": 10, "failed_count": 0}
            upgrade_engine.stability_golden_gate = lambda: {
                "passed": False,
                "case_count": 12,
                "passed_count": 11,
                "failed_count": 1,
                "failed_cases": ["route-freedom-protocol"],
            }

            result = upgrade_engine.step_post_install_eval(plan, ["zz_unit_stability_probe"])
        finally:
            upgrade_engine.knowledge_audit_gate = original_knowledge_gate
            upgrade_engine.benchmark_gate = original_benchmark_gate
            upgrade_engine.stability_golden_gate = original_stability_gate

        self.assertTrue(result["regressed"])
        self.assertEqual(result["reason"], "stability_golden_failed")
        self.assertEqual(plan.status, "rolled_back")
        self.assertFalse(tool_path.exists())
        self.assertEqual(result["rollback"]["removed"], ["zz_unit_stability_probe"])
        self.assertEqual(result["stability_golden"]["failed_cases"], ["route-freedom-protocol"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
