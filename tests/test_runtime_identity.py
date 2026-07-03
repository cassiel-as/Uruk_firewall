import unittest

from services.relay_protocol import format_relay_message
from services.runtime_identity import (
    RUNTIME_IDENTITY_GUARD,
    RUNTIME_IDENTITY_ID,
    RUNTIME_IDENTITY_LABEL,
    with_runtime_identity,
)


class RuntimeIdentityTests(unittest.TestCase):
    def test_identity_guard_names_uruk_protocol_carrier(self):
        self.assertEqual(RUNTIME_IDENTITY_ID, "uruk_protocol_carrier")
        self.assertIn(RUNTIME_IDENTITY_LABEL, RUNTIME_IDENTITY_GUARD)
        self.assertIn("你唔係 Claude Desktop", RUNTIME_IDENTITY_GUARD)
        self.assertIn("backend / 工具 / 載體通道", RUNTIME_IDENTITY_GUARD)

    def test_with_runtime_identity_is_idempotent(self):
        once = with_runtime_identity("system body")
        twice = with_runtime_identity(once)

        self.assertEqual(once, twice)
        self.assertTrue(once.startswith(RUNTIME_IDENTITY_GUARD))

    def test_relay_adapter_keeps_model_as_backend_channel(self):
        prompt = format_relay_message("claude", "You are a tool designer. python_code", relay_mode="tool_design")

        self.assertIn("Runtime identity: URUK protocol carrier", prompt)
        self.assertIn("Target model/app: Claude Desktop", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
