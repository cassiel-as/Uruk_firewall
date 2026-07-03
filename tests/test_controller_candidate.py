import unittest

from training.run_controller_candidate import load_examples, parse_decision


class ControllerCandidateTests(unittest.TestCase):
    def test_parse_decision_accepts_json_object(self):
        value, error = parse_decision('{"route_kind":"small_task"}')

        self.assertEqual(value["route_kind"], "small_task")
        self.assertIsNone(error)

    def test_parse_decision_extracts_fenced_or_prefixed_object(self):
        value, error = parse_decision('result:\\n{"route_kind":"deep_reasoning"}\\nend')

        self.assertEqual(value["route_kind"], "deep_reasoning")
        self.assertIsNone(error)

    def test_parse_decision_rejects_non_json(self):
        value, error = parse_decision("not json")

        self.assertEqual(value, {})
        self.assertIsNotNone(error)

    def test_test_split_is_nonempty_and_family_held_out(self):
        test_examples = load_examples("training/generated", split="test")
        train_examples = load_examples("training/generated", split="train")

        self.assertGreaterEqual(len(test_examples), 30)
        self.assertNotEqual(
            {item["example_id"] for item in test_examples},
            {item["example_id"] for item in train_examples},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
