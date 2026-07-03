import unittest

from file_service import fs


class FileServiceTreeTests(unittest.TestCase):
    def test_files_tree_exposes_categorized_knowledge_files(self):
        tree = fs.get_tree()
        files = {
            item["path"]
            for layer in tree.values()
            for item in layer.get("files", [])
        }

        expected = {
            "data/theory/coordinate_theory_paper.md",
            "data/theory/CIVILIZATION_ANCHORS.md",
            "data/theory/COORDINATE_THEORY_EXPANSION.md",
            "data/theory/coordinate_theory_integrated_EN_v3.md",
            "data/misc/data_supplement.md",
            "data/misc/gap_resolution.md",
            "data/causal_records/CAUSAL_RECORD_2024-01_to_2024-08.md",
            "data/causal_records/CAUSAL_RECORD_2024-09_to_2025-04.md",
            "data/causal_records/CAUSAL_RECORD_2025-05_to_2026-05_全中文.md",
            "config/protocol/references/module_t/MODULE_T_CALIBRATION_19141916.md",
            "config/protocol/references/module_t/MODULE_T_CALIBRATION_19391941.md",
            "config/protocol/references/module_t/MODULE_T_CALIBRATION_19791981.md",
        }
        self.assertTrue(expected <= files, expected - files)

    def test_new_canonical_file_roots_are_read_only(self):
        tree = fs.get_tree()
        by_path = {
            item["path"]: item
            for layer in tree.values()
            for item in layer.get("files", [])
        }

        self.assertTrue(by_path["data/theory/coordinate_theory_paper.md"]["readonly"])
        self.assertTrue(by_path["data/misc/data_supplement.md"]["readonly"])
        self.assertTrue(by_path["data/causal_records/CAUSAL_RECORD_2024-01_to_2024-08.md"]["readonly"])
        self.assertTrue(by_path["config/protocol/references/module_t/MODULE_T_CALIBRATION_19141916.md"]["readonly"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
