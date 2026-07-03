import unittest

from services.relay_protocol import (
    format_relay_message,
    infer_relay_mode,
    review_json_contract,
    tool_design_json_contract,
    upgrade_output_contract,
)


class RelayProtocolContractTests(unittest.TestCase):
    def test_upgrade_contract_uses_exact_plan_id(self):
        contract = upgrade_output_contract("upgrade-test-123", tool_count=2)

        self.assertIn("[UPGRADE_EXECUTION_PLAN:upgrade-test-123]", contract)
        self.assertIn("[TOOL_SPEC:upgrade-test-123]", contract)
        self.assertIn("Output exactly 2", contract)
        self.assertIn("execute(args: dict) -> dict", contract)

    def test_json_contracts_are_present(self):
        self.assertIn('"python_code"', tool_design_json_contract())
        self.assertIn('"pass"', review_json_contract())
        self.assertIn('"concerns"', review_json_contract())


class RelayProtocolAdapterTests(unittest.TestCase):
    upgrade_message = "[UPGRADE_PLAN:upgrade-test]\nNeed safe tool specs."

    def test_codex_adapter_uses_codex_envelope(self):
        wrapped = format_relay_message("codex", self.upgrade_message, "upgrade")

        self.assertIn("<CODEX_RESPONSE>", wrapped)
        self.assertIn("<CODEX_RELAY_REQUEST>", wrapped)
        self.assertIn("uruk-codex-upgrade", wrapped)
        self.assertIn("[UPGRADE_EXECUTION_PLAN:<plan_id>]", wrapped)
        self.assertIn(self.upgrade_message, wrapped)
        self.assertFalse(wrapped.lstrip().startswith("/uruk-relay"))

    def test_claude_adapter_uses_relay_without_codex_envelope(self):
        wrapped = format_relay_message("claude", self.upgrade_message, "upgrade")

        self.assertTrue(wrapped.lstrip().startswith("/uruk-relay"))
        self.assertIn("[URUK_MODEL_ADAPTER:claude]", wrapped)
        self.assertIn("[UPGRADE_EXECUTION_PLAN:<plan_id>]", wrapped)
        self.assertIn(self.upgrade_message, wrapped)
        self.assertNotIn("<CODEX_RESPONSE>", wrapped)

    def test_claude_code_adapter_does_not_use_codex_envelope(self):
        wrapped = format_relay_message("claude_code", self.upgrade_message, "upgrade")

        self.assertFalse(wrapped.lstrip().startswith("/uruk-relay"))
        self.assertNotIn("[URUK_MODEL_ADAPTER:claude_code]", wrapped)
        self.assertNotIn("[UPGRADE_EXECUTION_PLAN:<plan_id>]", wrapped)
        self.assertIn(self.upgrade_message, wrapped)
        self.assertNotIn("<CODEX_RESPONSE>", wrapped)

    def test_general_claude_keeps_simple_relay_prefix(self):
        self.assertEqual(format_relay_message("claude", "hello"), "/uruk-relay hello")

    def test_copilot_adapter_uses_copilot_request_and_canonical_contract(self):
        wrapped = format_relay_message("copilot", self.upgrade_message, "upgrade")

        self.assertIn("<COPILOT_RELAY_REQUEST>", wrapped)
        self.assertIn("[UPGRADE_EXECUTION_PLAN:<plan_id>]", wrapped)
        self.assertIn("Windows Copilot relay role", wrapped)
        self.assertIn(self.upgrade_message, wrapped)
        self.assertNotIn("<CODEX_RESPONSE>", wrapped)


class RelayModeInferenceTests(unittest.TestCase):
    def test_mode_inference(self):
        cases = {
            "upgrade": "[UPGRADE_PLAN:abc] design a tool",
            "tool_design": "Return python_code for this tool.",
            "review": '{"pass": true, "concerns": []} security review',
            "general": "normal chat",
        }

        for expected, message in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(infer_relay_mode(message), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
