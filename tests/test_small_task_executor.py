import asyncio
import unittest

from services.small_task_executor import extract_json, run_small_task


class SmallTaskExecutorTests(unittest.TestCase):
    def test_extract_json_finds_embedded_object(self):
        parsed = extract_json('prefix {"b": 2, "a": [1, 2]} suffix')

        self.assertTrue(parsed["ok"], parsed)
        self.assertEqual(parsed["value"], {"b": 2, "a": [1, 2]})

    def test_normalize_json_is_deterministic(self):
        result = asyncio.run(
            run_small_task(
                "normalize_json",
                'noise {"b": 2, "a": 1}',
                options={"indent": 0},
            )
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["source"], "deterministic")
        self.assertIn('"a": 1', result["text"])
        self.assertLess(result["text"].find('"a": 1'), result["text"].find('"b": 2'))

    def test_summarize_falls_back_when_small_model_unavailable(self):
        async def failing_chat(**kwargs):
            raise TimeoutError("unit timeout")

        result = asyncio.run(
            run_small_task(
                "summarize",
                "First sentence. Second sentence. Third sentence. Fourth sentence.",
                options={"sentences": 2},
                chat_fn=failing_chat,
            )
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["source"], "deterministic_fallback")
        self.assertEqual(result["text"], "First sentence. Second sentence.")
        self.assertTrue(result["warnings"])

    def test_answer_simple_uses_small_model(self):
        seen = {}

        async def fake_chat(**kwargs):
            seen.update(kwargs)
            return "Paris."

        result = asyncio.run(
            run_small_task(
                "answer_simple",
                "What is the capital of France?",
                chat_fn=fake_chat,
            )
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["source"], "small_model")
        self.assertEqual(result["text"], "Paris.")
        self.assertEqual(result["profile"], "local_language")
        self.assertEqual(seen["model"], "qwen3.5:4b")
        self.assertFalse(seen["think"])
        self.assertEqual(result["routing"]["authority"], "worker")

    def test_answer_simple_blocks_system_level_tasks(self):
        result = asyncio.run(
            run_small_task(
                "answer_simple",
                "upgrade system and install tool for Trinity",
            )
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["source"], "blocked")
        self.assertIn("full pipeline", result["error"])

    def test_answer_simple_blocks_coordinate_abstract_concepts(self):
        result = asyncio.run(
            run_small_task(
                "answer_simple",
                "咩係真理？",
            )
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["source"], "blocked")
        self.assertIn("full pipeline", result["error"])

    def test_classify_keyword_path_uses_low_level_classifier(self):
        result = asyncio.run(run_small_task("classify", "latest AI news today"))

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["type"], "search")
        self.assertEqual(result["profile"], "local_classifier")
        self.assertEqual(result["routing"]["authority"], "routing_only")

    def test_classify_reasoning_signal_stays_complex_without_model(self):
        result = asyncio.run(run_small_task("classify", "幫我比較兩個方案嘅長期風險"))

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["type"], "complex")
        self.assertEqual(result["source"], "keyword")

    def test_extract_entities_uses_language_worker_and_parses_json(self):
        async def fake_chat(**kwargs):
            return '{"people":["Ada"],"organizations":[],"locations":["London"],"dates":[],"topics":["computing"]}'

        result = asyncio.run(
            run_small_task(
                "extract_entities",
                "Ada discussed computing in London.",
                chat_fn=fake_chat,
            )
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["profile"], "local_language")
        self.assertEqual(result["data"]["people"], ["Ada"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
