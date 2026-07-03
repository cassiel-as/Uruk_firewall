import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.upgrade_report import (
    collect_upgrade_plans,
    derive_action_items,
    generate_self_upgrade_report,
    load_report,
)


class UpgradeReportTests(unittest.TestCase):
    def test_collect_upgrade_plans_compacts_status_and_steps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plans_dir = root / "data" / "upgrade_plans"
            plans_dir.mkdir(parents=True)
            (plans_dir / "upgrade-unit.json").write_text(json.dumps({
                "plan_id": "upgrade-unit",
                "mode": "audit",
                "relay_target": "codex",
                "created_at": "2026-06-01T00:00:00",
                "status": "failed",
                "summary": "unit failure",
                "gaps": [{"id": "gap"}],
                "tool_specs": [],
                "review_tool_specs": [],
                "installed_tools": [],
                "execution_contract": {},
                "executor_events": [],
                "steps": [
                    {"id": 1, "executor": "system", "action": "scan_tools", "status": "done"},
                    {"id": 2, "executor": "system", "action": "validate_code", "status": "failed"},
                ],
            }), encoding="utf-8")

            plans = collect_upgrade_plans(root=root)

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0]["plan_id"], "upgrade-unit")
            self.assertEqual(plans[0]["failed_steps"], ["validate_code"])
            self.assertEqual(plans[0]["gap_count"], 1)

    def test_generate_report_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plans_dir = root / "data" / "upgrade_plans"
            plans_dir.mkdir(parents=True)
            (plans_dir / "upgrade-unit.json").write_text(json.dumps({
                "plan_id": "upgrade-unit",
                "mode": "audit",
                "relay_target": "codex",
                "created_at": "2026-06-01T00:00:00",
                "status": "done",
                "summary": "unit complete",
                "gaps": [],
                "tool_specs": [],
                "review_tool_specs": [],
                "installed_tools": ["zz_unit_tool"],
                "execution_contract": {},
                "executor_events": [],
                "steps": [],
            }), encoding="utf-8")
            (root / "data" / "upgrade_log.jsonl").write_text(
                json.dumps({"tool_name": "zz_unit_tool", "plan_id": "upgrade-unit"}) + "\n",
                encoding="utf-8",
            )

            report = generate_self_upgrade_report(
                root=root,
                run_gates=False,
                run_prompt_regression=False,
                write=True,
            )

            self.assertIn(report["status"], {"healthy", "attention"})
            self.assertTrue(report["files"]["json_path"].endswith(".json"))
            self.assertTrue(report["files"]["markdown_path"].endswith(".md"))
            self.assertTrue((root / report["files"]["json_path"]).exists())
            self.assertTrue((root / report["files"]["markdown_path"]).exists())
            loaded = load_report(report["report_id"], root=root)
            self.assertEqual(loaded["report_id"], report["report_id"])

    def test_derive_action_items_flags_failed_plan_and_gate(self):
        items = derive_action_items(
            latest_plan={
                "plan_id": "upgrade-failed",
                "status": "failed",
                "summary": "relay failed",
                "failed_steps": ["design_tools"],
            },
            plans=[{"status": "failed"}, {"status": "rolled_back"}],
            upgrade_log=[],
            gates={"ok": False, "quick_eval": {"skipped": True, "reason": "no baseline"}},
            prompt_regression={"ok": True, "status": "passed", "diff": {"prompt_changed": False}},
        )

        titles = {item["title"] for item in items}
        self.assertIn("最新升級計劃狀態係 failed", titles)
        self.assertIn("self-upgrade 硬閘未通過", titles)
        self.assertTrue(any(item["priority"] == "P0" for item in items))


    def test_derive_action_items_flags_failed_stability_golden_gate(self):
        items = derive_action_items(
            latest_plan={
                "plan_id": "upgrade-done",
                "status": "done",
                "summary": "done",
                "installed_tools": ["unit_tool"],
            },
            plans=[],
            upgrade_log=[{"tool_name": "unit_tool"}],
            gates={
                "ok": False,
                "stability_golden": {
                    "passed": False,
                    "failed_cases": ["route-freedom-protocol"],
                },
                "quick_eval": {"skipped": False, "passed": True},
            },
            prompt_regression={"ok": True, "status": "passed", "diff": {"prompt_changed": False}},
        )

        stability_items = [item for item in items if item["title"] == "stability golden cases failed"]
        self.assertTrue(stability_items)
        self.assertEqual(stability_items[0]["priority"], "P0")
        self.assertIn("route-freedom-protocol", stability_items[0]["detail"])

    def test_historical_failed_plan_is_attention_not_current_blocker(self):
        items = derive_action_items(
            latest_plan={
                "plan_id": "upgrade-old-failed",
                "status": "failed",
                "created_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
                "summary": "old relay timeout",
                "failed_steps": [],
            },
            plans=[],
            upgrade_log=[{"tool_name": "existing"}],
            gates={"ok": True, "quick_eval": {"skipped": False, "passed": True}},
            prompt_regression={"ok": True, "status": "passed", "diff": {"prompt_changed": False}},
        )

        self.assertFalse(any(item["priority"] == "P0" for item in items))
        self.assertTrue(any("歷史 failed" in item["title"] for item in items))


if __name__ == "__main__":
    unittest.main(verbosity=2)
