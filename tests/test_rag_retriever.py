"""
RAG Phase 2 — unit tests for indexer + retriever (v8.30).

Covers:
  - tokenisation (Latin + CJK mixed)
  - section-aware chunking
  - recursive split with overlap
  - TF-IDF build & shape
  - retriever fail-safe when index missing (singleton returns None)
  - retriever returns relevant chunks for canonical queries
  - format_for_prompt produces injectable block
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from services import rag_indexer, rag_retriever  # noqa: E402


class TokenizeTests(unittest.TestCase):
    def test_latin_words(self) -> None:
        self.assertEqual(
            rag_indexer.tokenize("LIE_COST Landauer entropy"),
            ["lie_cost", "landauer", "entropy"],
        )

    def test_cjk_per_char_tokenisation(self) -> None:
        toks = rag_indexer.tokenize("黑死病崩潰比率")
        self.assertEqual(toks, ["黑", "死", "病", "崩", "潰", "比", "率"])

    def test_mixed_cjk_latin(self) -> None:
        toks = rag_indexer.tokenize("Equation 1 技術躍遷 397")
        self.assertIn("equation", toks)
        self.assertIn("1", toks)
        self.assertIn("技", toks)
        self.assertIn("躍", toks)
        self.assertIn("397", toks)

    def test_date_tokens_are_kept(self) -> None:
        toks = rag_indexer.tokenize("2026-03-08 3月8號")
        for token in ["2026", "03", "08", "3", "8", "月", "號"]:
            self.assertIn(token, toks)

    def test_empty(self) -> None:
        self.assertEqual(rag_indexer.tokenize(""), [])


class ChunkingTests(unittest.TestCase):
    def test_section_split_picks_up_headings(self) -> None:
        text = "preamble line\n\n## Section A\nbody A\n\n### Section B\nbody B"
        out = rag_indexer.section_split(text)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0][0], "preamble")
        self.assertTrue(out[1][0].startswith("## "))
        self.assertTrue(out[2][0].startswith("### "))

    def test_recursive_split_short_text_passthrough(self) -> None:
        out = rag_indexer.recursive_split("short text under 700 chars")
        self.assertEqual(out, ["short text under 700 chars"])

    def test_recursive_split_long_text_with_overlap(self) -> None:
        # 2 KB string of repeated char + paragraph breaks
        text = ("foo " * 200 + "\n\n" + "bar " * 200 + "\n\n" + "baz " * 200)
        out = rag_indexer.recursive_split(text, max_chars=700, overlap=150)
        self.assertGreater(len(out), 1)
        # Each chunk respects max_chars+overlap budget loosely
        for chunk in out:
            self.assertLessEqual(len(chunk), 900)  # max + paragraph-snap slack


class TfIdfBuildTests(unittest.TestCase):
    def test_tfidf_normalised_to_unit_length(self) -> None:
        chunks = [
            {"text": "alpha beta beta gamma"},
            {"text": "beta gamma delta"},
            {"text": "alpha delta delta epsilon"},
        ]
        rag_indexer.compute_tfidf(chunks)
        for c in chunks:
            norm = sum(v * v for v in c["tfidf"].values()) ** 0.5
            self.assertAlmostEqual(norm, 1.0, places=5)

    def test_tfidf_idf_higher_for_rare_term(self) -> None:
        chunks = [
            {"text": "alpha alpha alpha rare"},
            {"text": "alpha alpha"},
            {"text": "alpha alpha alpha alpha"},
        ]
        idf = rag_indexer.compute_tfidf(chunks)
        # 'rare' appears in 1 doc, 'alpha' appears in 3 → idf(rare) > idf(alpha)
        self.assertGreater(idf["rare"], idf["alpha"])

    def test_kairos_active_indexed_instead_of_full_updated_log(self) -> None:
        sources = {
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in rag_indexer._collect_sources()
        }
        self.assertIn("data/kairos/KAIROS_ACTIVE.md", sources)
        self.assertIn("data/kairos/KAIROS_ARCHIVE_INDEX.md", sources)
        self.assertNotIn("data/kairos/KAIROS_LOG_UPDATED_v8.md", sources)

    def test_system_docs_and_skill_specs_are_indexed(self) -> None:
        sources = {
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in rag_indexer._collect_sources()
        }
        self.assertIn("README.md", sources)
        self.assertIn("services/README.md", sources)
        self.assertIn("docs/model-onboarding.md", sources)
        self.assertIn("skills/uruk-self-upgrade/SKILL.md", sources)
        self.assertIn("codex-upgrade-SKILL.md", sources)
        self.assertNotIn("skills/test-skill/SKILL.md", sources)

    def test_runtime_summaries_are_indexed_instead_of_raw_runtime_payloads(self) -> None:
        sources = {
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in rag_indexer._collect_sources()
        }
        self.assertIn("data/index/EXPERIMENT_INDEX.md", sources)
        self.assertIn("data/index/HARNESS_EPISODE_INDEX.md", sources)
        self.assertIn("data/index/UPGRADE_HISTORY_INDEX.md", sources)
        self.assertNotIn("data/experiments/EXPERIMENT_011_FULL.md", sources)
        self.assertFalse(any(s.startswith("data/harness_episodes/") for s in sources))
        self.assertFalse(any(s.startswith("data/upgrade_plans/") for s in sources))

    def test_supplements_and_causal_records_are_indexed(self) -> None:
        sources = {
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in rag_indexer._collect_sources()
        }
        self.assertIn("data/misc/data_supplement.md", sources)
        self.assertIn("data/misc/gap_resolution.md", sources)
        self.assertIn("data/causal_records/CAUSAL_RECORD_2024-01_to_2024-08.md", sources)
        self.assertIn("data/causal_records/CAUSAL_RECORD_2024-09_to_2025-04.md", sources)
        self.assertIn("data/causal_records/CAUSAL_RECORD_2025-05_to_2026-05_全中文.md", sources)


class RetrieverIntegrationTests(unittest.TestCase):
    """These rely on the index built by `py -m services.rag_indexer --build`.

    If the index files don't exist, the singleton returns None and tests skip.
    """

    def setUp(self) -> None:
        rag_retriever.reset_for_test()
        self.r = rag_retriever.get_retriever()

    def test_retriever_loads_or_returns_none(self) -> None:
        # If index exists, retriever loads; otherwise None.
        if self.r is None:
            self.skipTest("RAG index not built — run services/rag_indexer.py --build first")
        self.assertTrue(self.r.loaded)
        self.assertGreater(len(self.r.chunks), 0)
        self.assertGreater(len(self.r.idf), 0)
        self.assertEqual(self.r.manifest.get("method"), "tfidf")

    def test_carrier_query_hits_carrier_epistemics(self) -> None:
        if self.r is None:
            self.skipTest("RAG index not built")
        results = self.r.retrieve(
            "Cassiel as carrier first-person false humility", k=3
        )
        self.assertGreater(len(results), 0)
        top_sources = {r["source_file"] for r in results}
        # carrier_epistemics.md should be at or near the top
        self.assertTrue(
            any("carrier_epistemics" in s for s in top_sources),
            f"expected carrier_epistemics.md in top hits, got {top_sources}",
        )

    def test_equation_query_hits_eqn_or_module_t(self) -> None:
        if self.r is None:
            self.skipTest("RAG index not built")
        results = self.r.retrieve(
            "Equation 1 tech leap 397 0.279 next year", k=3
        )
        self.assertGreater(len(results), 0)
        top_sources = {r["source_file"] for r in results}
        # Should land on URUK_README / MASTER_INDEX / module_t
        relevant = ("URUK_README", "MASTER_INDEX", "module_t", "RAG_SUMMARY")
        self.assertTrue(
            any(any(k in s for k in relevant) for s in top_sources),
            f"expected equations corpus in top hits, got {top_sources}",
        )

    def test_format_for_prompt_returns_block_with_marker(self) -> None:
        if self.r is None:
            self.skipTest("RAG index not built")
        block = self.r.format_for_prompt(
            "eight laws LIE_COST FREEDOM_LOSS", k=3
        )
        self.assertIn("RAG retrieval", block)
        self.assertIn("engine=tfidf", block)
        self.assertGreater(len(block), 100)

    def test_empty_query_returns_empty(self) -> None:
        if self.r is None:
            self.skipTest("RAG index not built")
        self.assertEqual(self.r.retrieve(""), [])
        self.assertEqual(self.r.format_for_prompt(""), "")

    def test_unmatched_query_returns_empty(self) -> None:
        if self.r is None:
            self.skipTest("RAG index not built")
        # Query of pure out-of-vocab Latin tokens
        results = self.r.retrieve("xyzzyx qqqqq blorft", k=3)
        # If all tokens are out-of-IDF, result is empty
        self.assertEqual(results, [])

    def test_char_budget_respected(self) -> None:
        if self.r is None:
            self.skipTest("RAG index not built")
        results = self.r.retrieve("trinity father son spirit", k=10,
                                  max_total_chars=400)
        total = sum(len(r["text"]) for r in results)
        # Allow first chunk to overshoot if it's bigger than the cap
        # (we only enforce cap on the boundary, not strict slice).
        self.assertGreater(len(results), 0)
        self.assertLessEqual(total, 1200)  # generous upper bound

    def test_kairos_date_query_hits_archive_index(self) -> None:
        if self.r is None:
            self.skipTest("RAG index not built")
        results = self.r.retrieve("3月8號發生過咩事", k=5)
        self.assertGreater(len(results), 0)
        sources = {r["source_file"] for r in results}
        self.assertIn("data/kairos/KAIROS_ARCHIVE_INDEX.md", sources)
        self.assertTrue(
            all("data/causal_db/" not in r["source_file"] for r in results[:3])
        )
        joined = "\n".join(r["text"] for r in results)
        self.assertIn("2026-03-08", joined)


class SilentFallbackTests(unittest.TestCase):
    """If index doesn't exist, get_retriever() must return None, not raise."""

    def test_get_retriever_with_bad_path(self) -> None:
        from services.rag_retriever import RagRetriever
        r = RagRetriever(index_dir=Path("/nonexistent/rag/index"))
        self.assertFalse(r.loaded)
        self.assertEqual(r.retrieve("anything"), [])
        self.assertEqual(r.format_for_prompt("anything"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
