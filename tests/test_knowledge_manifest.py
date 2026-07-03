import json
import tempfile
import unittest
from pathlib import Path

from services.knowledge_manifest import ROOT, audit_knowledge, resolve_ref
from services import rag_retriever
from trinity_console import TrinityConsole, _KNOWLEDGE_TRACE_CTX


class KnowledgeManifestRepositoryTests(unittest.TestCase):
    def test_coordinate_alias_resolves_to_manifest_document(self):
        docs = resolve_ref("theory:\u5ea7\u6a19\u8aaa", root=ROOT)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].id, "theory.coordinate.v5")
        self.assertEqual(docs[0].path, "data/theory/\u5ea7\u6a19\u8aaa_v5_updated.md")
        self.assertTrue(docs[0].legacy_paths)
        self.assertTrue(docs[0].abs_path(ROOT).exists())

        card_docs = resolve_ref("theory:coordinate_cards", root=ROOT)
        self.assertEqual(len(card_docs), 1)
        self.assertEqual(card_docs[0].id, "theory.coordinate.cards")

    def test_kairos_active_resolves_to_curated_memory(self):
        docs = resolve_ref("kairos:active", root=ROOT)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].id, "kairos.active")
        self.assertTrue(docs[0].canonical)

        updated = resolve_ref("kairos:updated", root=ROOT)
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0].id, "kairos.updated_archive")
        self.assertFalse(updated[0].canonical)

    def test_cau_number_and_protocol_alias_resolve(self):
        cau_docs = resolve_ref("cau:011", root=ROOT)
        self.assertEqual(len(cau_docs), 1)
        self.assertTrue(cau_docs[0].path.endswith("CAU-011_AI_EMERGENCE.md"))

        protocol_docs = resolve_ref("protocol:source_registry", root=ROOT)
        self.assertEqual(len(protocol_docs), 1)
        self.assertEqual(protocol_docs[0].id, "protocol.source_coordinate_registry")

    def test_supplements_causal_records_and_module_t_resolve(self):
        gap_docs = resolve_ref("misc:gap", root=ROOT)
        self.assertEqual(len(gap_docs), 1)
        self.assertEqual(gap_docs[0].id, "misc.gap_resolution")

        record_docs = resolve_ref("causal_record:2025_05_to_2026_05", root=ROOT)
        self.assertEqual(len(record_docs), 1)
        self.assertEqual(record_docs[0].id, "causal_record.2025_05_to_2026_05")

        module_docs = resolve_ref("module_t:1914-1916", root=ROOT)
        self.assertEqual(len(module_docs), 1)
        self.assertEqual(module_docs[0].id, "module_t.1914_1916")

    def test_system_docs_and_skill_specs_resolve(self):
        docs = resolve_ref("system:service_map", root=ROOT)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].id, "system.services_readme")
        self.assertTrue(docs[0].canonical)

        skill_docs = resolve_ref("skill:uruk_self_upgrade", root=ROOT)
        self.assertEqual(len(skill_docs), 1)
        self.assertEqual(skill_docs[0].id, "skill.uruk_self_upgrade")
        self.assertTrue(skill_docs[0].canonical)

    def test_runtime_summary_indexes_resolve(self):
        experiment_docs = resolve_ref("experiment:experiments", root=ROOT)
        self.assertEqual(len(experiment_docs), 1)
        self.assertEqual(experiment_docs[0].id, "index.experiments")
        self.assertTrue(experiment_docs[0].canonical)

        harness_docs = resolve_ref("harness:episodes", root=ROOT)
        self.assertEqual(len(harness_docs), 1)
        self.assertEqual(harness_docs[0].id, "index.harness_episodes")
        self.assertTrue(harness_docs[0].canonical)

        upgrade_docs = resolve_ref("upgrade:upgrade_history", root=ROOT)
        self.assertEqual(len(upgrade_docs), 1)
        self.assertEqual(upgrade_docs[0].id, "index.upgrade_history")
        self.assertTrue(upgrade_docs[0].canonical)

    def test_repository_audit_has_no_fatal_manifest_issues(self):
        report = audit_knowledge(root=ROOT)
        self.assertEqual(report["summary"]["issues"]["P0"], 0, report["issues"])
        self.assertEqual(report["cau_structure"]["checked"], 12)
        self.assertEqual(report["cau_structure"]["failed"], 0, report["issues"])

    def test_trinity_load_context_uses_manifest_alias_before_glob_fallback(self):
        console = TrinityConsole.__new__(TrinityConsole)
        console.data_dir = ROOT / "data"
        console.config_dir = ROOT / "config"

        block = console._load_context(["theory:\u5ea7\u6a19\u8aaa"])

        self.assertIn("doc_id=theory.coordinate.v5", block)
        self.assertGreater(len(block), 1000)

    def test_rag_block_records_actual_knowledge_trace(self):
        token = _KNOWLEDGE_TRACE_CTX.set([])
        try:
            console = TrinityConsole.__new__(TrinityConsole)
            block = console.rag_block("KAIROS_CORE physical anchor", k=2, max_chars=1200)
            if not block:
                self.skipTest("RAG index not built")
            trace = console.get_knowledge_trace()
        finally:
            _KNOWLEDGE_TRACE_CTX.reset(token)

        self.assertGreater(len(trace), 0)
        rag_entry = next((entry for entry in trace if entry["source"] == "rag_block"), None)
        self.assertIsNotNone(rag_entry)
        self.assertGreater(len(rag_entry["hits"]), 0)
        self.assertIn("source_file", rag_entry["hits"][0])

    def test_manual_ref_load_records_knowledge_trace(self):
        token = _KNOWLEDGE_TRACE_CTX.set([])
        try:
            console = TrinityConsole.__new__(TrinityConsole)
            console.data_dir = ROOT / "data"
            console.config_dir = ROOT / "config"
            block = console._load_context(["cau:011"])
            trace = console.get_knowledge_trace()
        finally:
            _KNOWLEDGE_TRACE_CTX.reset(token)

        self.assertIn("CAU-011_AI_EMERGENCE", block)
        self.assertEqual(trace[0]["source"], "manual_ref")
        self.assertTrue(trace[0]["hits"][0]["source_file"].endswith("CAU-011_AI_EMERGENCE.md"))

    def test_knowledge_health_summary_is_clean(self):
        console = TrinityConsole.__new__(TrinityConsole)
        console.data_dir = ROOT / "data"
        health = console.knowledge_health_summary()
        self.assertTrue(health["clean"], health)

    def test_rag_retriever_loads_manifest_metadata(self):
        rag_retriever.reset_for_test()
        retriever = rag_retriever.get_retriever()
        if retriever is None:
            self.skipTest("RAG index not built")
        doc = retriever.knowledge_docs.get("data/core/KAIROS_CORE.md")
        self.assertIsNotNone(doc)
        self.assertEqual(doc["id"], "core.kairos")

        card_doc = retriever.knowledge_docs.get("data/theory/COORDINATE_KNOWLEDGE_CARDS.md")
        self.assertIsNotNone(card_doc)
        self.assertEqual(card_doc["id"], "theory.coordinate.cards")

        system_doc = retriever.knowledge_docs.get("services/README.md")
        self.assertIsNotNone(system_doc)
        self.assertEqual(system_doc["id"], "system.services_readme")

        skill_doc = retriever.knowledge_docs.get("skills/uruk-self-upgrade/SKILL.md")
        self.assertIsNotNone(skill_doc)
        self.assertEqual(skill_doc["id"], "skill.uruk_self_upgrade")

        upgrade_index_doc = retriever.knowledge_docs.get("data/index/UPGRADE_HISTORY_INDEX.md")
        self.assertIsNotNone(upgrade_index_doc)
        self.assertEqual(upgrade_index_doc["id"], "index.upgrade_history")


class KnowledgeManifestTempAuditTests(unittest.TestCase):
    def test_audit_detects_duplicate_alias_and_rag_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "theory").mkdir(parents=True)
            (root / "data" / "rag_index").mkdir(parents=True)
            a = root / "data" / "theory" / "a.md"
            b = root / "data" / "theory" / "b.md"
            a.write_text("# A\nalpha\n", encoding="utf-8")
            b.write_text("# B\nbeta\n", encoding="utf-8")
            (root / "data" / "knowledge_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "collections": [],
                        "documents": [
                            {
                                "id": "theory.a",
                                "path": "data/theory/a.md",
                                "layer": "theory",
                                "canonical": True,
                                "status": "active",
                                "aliases": ["same"],
                                "ref_namespaces": ["theory"],
                            },
                            {
                                "id": "theory.b",
                                "path": "data/theory/b.md",
                                "layer": "theory",
                                "canonical": True,
                                "status": "active",
                                "aliases": ["same"],
                                "ref_namespaces": ["theory"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "rag_index" / "manifest.json").write_text(
                json.dumps(
                    {
                        "built_at": "unit",
                        "n_chunks": 1,
                        "source_hashes": {"data/theory/a.md": "badbadbadbadbadb"},
                    }
                ),
                encoding="utf-8",
            )

            report = audit_knowledge(root=root)
            codes = {issue["code"] for issue in report["issues"]}

            self.assertIn("duplicate_canonical_alias", codes)
            self.assertIn("rag_stale_source", codes)
            self.assertIn("rag_missing_source", codes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
