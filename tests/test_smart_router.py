import unittest

from services.smart_router import Backend, route


class SmartRouterTests(unittest.TestCase):
    def test_windows_context_routes_to_copilot_when_available(self):
        backend = route(
            "Please inspect this Windows screenshot and tell me which setting is wrong.",
            {
                "claude_desktop": True,
                "codex_desktop": True,
                "copilot_desktop": True,
                "ollama": True,
                "api": True,
            },
        )

        self.assertEqual(backend, Backend.COPILOT_DESKTOP)

    def test_code_task_still_prefers_codex_over_copilot(self):
        backend = route(
            "Fix this Python bug: def broken(: pass",
            {
                "claude_desktop": True,
                "codex_desktop": True,
                "copilot_desktop": True,
                "ollama": True,
                "api": True,
            },
        )

        self.assertEqual(backend, Backend.CODEX_DESKTOP)

    def test_protocol_concepts_do_not_route_to_small_local_first(self):
        backend = route(
            "咩係愛？",
            {
                "claude_desktop": False,
                "codex_desktop": False,
                "copilot_desktop": False,
                "ollama": True,
                "api": True,
            },
        )

        self.assertEqual(backend, Backend.API)

    def test_protocol_concepts_do_not_fall_back_to_local_only(self):
        backend = route(
            "What is freedom?",
            {
                "claude_desktop": False,
                "codex_desktop": False,
                "copilot_desktop": False,
                "ollama": True,
                "api": False,
            },
        )

        self.assertNotEqual(backend, Backend.OLLAMA)

    def test_code_decisions_do_not_fall_back_to_local_only(self):
        backend = route(
            "Fix this Python bug: def broken(: pass",
            {
                "claude_desktop": False,
                "codex_desktop": False,
                "copilot_desktop": False,
                "ollama": True,
                "api": False,
            },
        )

        self.assertEqual(backend, Backend.CODEX_DESKTOP)

    def test_short_reasoning_request_does_not_use_local_worker(self):
        backend = route(
            "幫我比較兩個方案嘅長期風險",
            {
                "claude_desktop": False,
                "codex_desktop": True,
                "copilot_desktop": False,
                "ollama": True,
                "api": False,
            },
        )

        self.assertEqual(backend, Backend.CODEX_DESKTOP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
