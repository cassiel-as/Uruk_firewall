import json
import shutil
import tempfile
import unittest
from pathlib import Path

from services.coordinate_index import (
    INDEX_REL,
    build_coordinate_index,
    get_coordinate_index,
    search_coordinate_index,
)


ROOT = Path(__file__).resolve().parent.parent


class CoordinateIndexTests(unittest.TestCase):
    def test_builds_and_searches_coordinate_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            theory_dir = root / "data" / "theory"
            theory_dir.mkdir(parents=True)
            shutil.copy(
                ROOT / "data" / "theory" / "coordinate_knowledge_cards.json",
                theory_dir / "coordinate_knowledge_cards.json",
            )
            shutil.copy(
                ROOT / "data" / "theory" / "COORDINATE_KNOWLEDGE_CARDS.md",
                theory_dir / "COORDINATE_KNOWLEDGE_CARDS.md",
            )

            index = build_coordinate_index(root, write=True)
            hits = search_coordinate_index(root, "upgrade harness trace", limit=4)

            self.assertGreater(index["card_count"], 0)
            self.assertTrue((root / INDEX_REL).exists())
            self.assertTrue(any(hit["id"] == "coordinate.upgrade.value" for hit in hits))

            loaded = get_coordinate_index(root)
            self.assertEqual(loaded["source_sha256"], index["source_sha256"])

    def test_index_json_shape_is_stable(self):
        index = build_coordinate_index(ROOT, write=False)

        self.assertIn("cards", index)
        self.assertIn("trigger_index", index)
        first = index["cards"][0]
        self.assertIn("id", first)
        self.assertIn("keywords", first)
        json.dumps(index, ensure_ascii=False)

    def test_explicit_triggers_survive_keyword_truncation(self):
        index = build_coordinate_index(ROOT, write=False)
        card = next(item for item in index["cards"] if item["id"] == "coordinate.freedom.entropy")

        self.assertIn("自由", card["keywords"])

    def test_freedom_concept_card_is_searchable(self):
        hits = search_coordinate_index(ROOT, "咩係自由？", limit=4)

        self.assertIn(
            "coordinate.freedom.entropy",
            {hit["id"] for hit in hits},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
