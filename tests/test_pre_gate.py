import asyncio
import unittest

from services.pre_gate import classify


class PreGateTests(unittest.TestCase):
    def test_freedom_is_forced_complex(self):
        result = asyncio.run(classify("咩係自由？"))

        self.assertEqual(result["type"], "complex")
        self.assertEqual(result["source"], "keyword")

    def test_other_abstract_concepts_are_forced_complex(self):
        result = asyncio.run(classify("咩係真理？"))

        self.assertEqual(result["type"], "complex")
        self.assertEqual(result["source"], "keyword")


if __name__ == "__main__":
    unittest.main(verbosity=2)
