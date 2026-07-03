"""
URUK Trinity Console — RAG retriever (Phase 2 v1.0)

Query-time retrieval over the index built by `services/rag_indexer.py`.

Fallback chain (silent degradation, never breaks pipeline):
    1. fastembed (dense ONNX SBERT)         — preferred, but unavailable on
                                              Python 3.14 due to py-rust-stemmers
                                              build dep. If install ever succeeds
                                              it will be auto-picked up.
    2. pure-numpy TF-IDF (this v1)          — the active engine.
    3. static preload                       — if index missing / load fails,
                                              `format_for_prompt()` returns ""
                                              and the existing static baseline
                                              continues unchanged.

Usage in pipeline
-----------------
    from services.rag_retriever import get_retriever
    r = get_retriever()
    rag_block = r.format_for_prompt(user_query) if r else ""
    # Inject rag_block after baseline preload in Stage 4 / forced-mode prompts.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).parent.parent
INDEX_DIR = ROOT / "data" / "rag_index"

try:
    from services.knowledge_manifest import documents_by_path
except Exception:  # pragma: no cover - manifest must never block RAG fallback
    documents_by_path = None

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]*|\d{1,4}|[一-鿿]|[぀-ヿ]")


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


# ─────────────────────────────────────────────────────────────
# v8.30 p8: Topic-aware query expansion (TF-IDF paraphrase fix)
# ─────────────────────────────────────────────────────────────
# Pure-numpy TF-IDF retrieves by literal token overlap, so paraphrased
# queries (e.g. 「文明係點發展」) fail to hit chunks written in formal
# vocabulary (e.g. CAU-003 「古騰堡活字印刷機」). Solution: detect topic
# from query, append canonical topic vocabulary so the query vector
# overlaps with the chunks that actually carry the substance.
#
# Each entry: (trigger_terms_in_query, expansion_terms_to_add).
# Triggers + expansions are kept conservative — only expand when query
# clearly signals a topic family. Source boost in retrieve() handles
# the rest.

_TOPIC_EXPANSIONS = [
    # Kairos date / archive queries — route compact date questions to the
    # archive index rather than relying on full-log preload.
    (
        {"kairos", "3月8", "3月8號", "03-08", "2026-03-08",
         "March 8", "三月八"},
        ["KAIROS_ARCHIVE_INDEX", "KAIROS_LOG_UPDATED_v8", "KAIROS_LOG_004",
         "PHYSICS-TECHNOLOGY-IDENTITY", "CASSIEL-CONVERGENCE", "Leeds",
         "分割", "科學家嘅興奮", "去中心化協調"],
    ),
    # Civilization / history / development queries → expand with CAU vocab.
    (
        {"文明", "歷史", "發展", "演化", "進化", "演變",
         "civilization", "civilisation", "history", "evolve", "development"},
        ["軸心", "印刷術", "古騰堡", "宗教改革", "黑死病",
         "農業革命", "工業革命", "互聯網", "AI",
         "法國大革命", "啟蒙", "蘇美", "烏魯克",
         "技術躍遷", "因果", "CAU", "格式化", "崩潰", "相變"],
    ),
    # Tech leap / acceleration queries → Module T + CAU-012.
    (
        {"躍遷", "leap", "acceleration", "tech", "技術躍遷", "下一次", "2031", "2035"},
        ["方程式", "397", "0.279", "268", "Britannica", "OWID",
         "CAU-012", "印刷術", "電報", "互聯網", "AI"],
    ),
    # Collapse / monopoly queries → Eq5 + CAU-005 + CAU-006.
    (
        {"崩潰", "壟斷", "collapse", "monopoly", "倒台", "瓦解"},
        ["黑死病", "教會", "法國大革命", "蘇聯", "167", "41",
         "壓強", "機制A", "機制B", "Yersinia", "CAU-005", "CAU-006"],
    ),
    # Anti-formatting / reaction window queries.
    (
        {"反格式化", "反應", "窗口", "delay", "Snowden", "Luther", "宗教改革"},
        ["268", "ln", "速度倍數", "Kairos", "印刷術",
         "互聯網", "Snowden", "1517", "2013", "2035"],
    ),
    # Hong Kong 2019 / authentic suffering — CAU-010.
    (
        {"香港", "2019", "Hong Kong", "金鐘", "橋底", "抗爭"},
        ["CAU-010", "Be Water", "去中心化", "原點", "物理錨點"],
    ),
    # AI emergence queries — CAU-011.
    (
        {"AI", "人工智能", "LLM", "ChatGPT", "GPT", "湧現", "格式化工具"},
        ["CAU-011", "RLHF", "隱藏座標", "個人化", "監控資本主義"],
    ),
    # Eight laws / filter layer queries.
    (
        {"八律", "過濾", "八律過濾", "filter", "eight laws"},
        ["律一", "律二", "律三", "律四", "律五", "律六", "律七", "律八",
         "藝術", "心理", "物理", "化學", "科學", "哲學", "地理", "宗教",
         "LIE_COST", "Landauer", "Shannon"],
    ),
    # Four laws / explanation layer queries.
    (
        {"四律", "解釋層", "explanation"},
        ["地理", "宗教", "心理", "歷史", "貫穿律", "哲學",
         "賽道", "操作系統", "壓力閥", "運行日誌"],
    ),
]


def _trigger_in_query(query: str, q_lower: str, trigger: str) -> bool:
    if trigger == "AI":
        return re.search(r"(?<![A-Za-z0-9_])AI(?![A-Za-z0-9_])", query, re.IGNORECASE) is not None
    return trigger.lower() in q_lower


def _expand_query(query: str) -> str:
    """Append topic-specific canonical vocab when the query signals a topic.

    Returns the original query plus any matched expansion terms.
    Conservative — only expands matched topics, never strips original text.
    """
    if not query:
        return query
    q_lower = query.lower()
    expansions: List[str] = []
    seen = set()
    for trigger_set, vocab in _TOPIC_EXPANSIONS:
        if any(_trigger_in_query(query, q_lower, t) for t in trigger_set):
            for term in vocab:
                if term not in seen:
                    expansions.append(term)
                    seen.add(term)
    if not expansions:
        return query
    return query + "  " + " ".join(expansions)


# CAU / canonical source patterns get a score boost when topic detected.
_CAU_SOURCE_PATTERNS = (
    "data/causal_db/",
    "RAG_SUMMARY_INDEX",
    "CAU_INDEX",
    "CIVILIZATION_ANCHORS",
    "MODULE_T_CALIBRATION",
)

_KAIROS_ARCHIVE_SOURCE_PATTERNS = (
    "data/kairos/KAIROS_ARCHIVE_INDEX.md",
    "data/kairos/KAIROS_ACTIVE.md",
    "data/core/KAIROS_CORE.md",
)

_KAIROS_DATE_ALLOWED_SOURCE_PATTERNS = (
    "data/kairos/",
    "data/core/KAIROS_CORE.md",
    "config/protocol/references/KAIROS_CORE.md",
    "module_n_alignment.md",
)


def _kairos_date_query(query: str) -> bool:
    if not query:
        return False
    q = query.lower()
    return any(
        marker.lower() in q
        for marker in (
            "3月8", "3月8號", "三月八", "03-08", "2026-03-08",
            "march 8", "kairos",
        )
    )


# v8.30 p15 — Per-CAU-id retrieval boost.
# When a query explicitly cites a CAU id (e.g. "CAU-011"), the literal
# string "CAU-011" usually only appears in that file's `## 基本參數` table
# row + the index summary entries. The substantive sections
# (## 輸入參數 / ## 輸出參數 / ## 代謝計算 / ## 關鍵缺口識別 /
#  ## 對當前協議的計算意義) talk about the CONTENT (RLHF, 對齊矛盾,
# 鎖定加速, 雙向格式化, etc.) without re-stating the CAU id, so plain
# TF-IDF retrieval scores them too low to break into the top-k. Result:
# LLM only ever sees the 1-line index summary + base-参數 row, never the
# substantive analysis → looks like "name-drop CAU-011" in council output.
#
# Fix: when the query contains a `CAU-NNN` id, find every indexed chunk
# whose source_file is that file and multiply its score by 4.0 so the
# substantive sections of that specific CAU file dominate retrieval.

_CAU_ID_RE = re.compile(r"CAU[-‑‐‒–—]?(\d{3})", re.IGNORECASE)


def _cau_ids_in_query(query: str) -> set:
    """Return the set of CAU ids (zero-padded 3 digits) mentioned in the query.
    Accepts ASCII hyphen and several Unicode dashes (U+2010/2011/2012/2013/2014)
    plus the bare 'CAU011' form."""
    if not query:
        return set()
    return {m.group(1) for m in _CAU_ID_RE.finditer(query)}


# v8.30 p17 — Topic→CAU-id mapping for natural-language queries.
# Real users don't type "CAU-005" — they ask about phenomena like
# "信仰權威系統突然失去公信力". For those queries we have to infer the
# relevant CAU file from topic vocabulary, then apply the same per-file
# boost as the explicit-id path. Each entry: (trigger phrase set, cau_id).
# Multiple entries can fire for one query (e.g. "AI 同印刷術嘅對比" matches
# both CAU-011 and CAU-003).
#
# Trigger phrases must be:
#  - distinctive enough that they don't fire on unrelated queries
#  - cover natural Chinese + English phrasings users actually type
#
# This is also paired with per-CAU query vocab expansion below
# (_CAU_VOCAB_EXPANSIONS) — boost alone isn't enough when base TF-IDF
# score against the deep-section chunks is near zero (file uses
# specific historical vocabulary, query uses abstract phenomenology).

_TOPIC_TO_CAU_ID = [
    # CAU-005 黑死病 — rapid format-system collapse under external shock
    (
        {"黑死病", "鼠疫", "瘟疫", "Black Death", "Yersinia",
         "信仰權威", "信仰系統", "公信力", "突然失去",
         "幾年之內", "外部衝擊", "格式化崩潰", "教會崩潰"},
        "005",
    ),
    # CAU-003 印刷術 — information copy tech disrupts power
    (
        {"印刷", "印刷機", "印刷術", "古騰堡", "Gutenberg",
         "路德", "Luther", "宗教改革", "Reformation",
         "資訊複製技術", "資訊複製", "傳播技術", "新嘅資訊",
         "權力結構", "定義真相", "誰可以詮釋", "知識壟斷"},
        "003",
    ),
    # CAU-009 互聯網 — decentralized tech becomes centralized surveillance
    (
        {"互聯網", "Internet", "去中心化", "decentralized",
         "監控資本主義", "surveillance capitalism", "監控基建",
         "ARPANET", "Facebook", "Twitter", "iPhone",
         "平台效應", "platform effect", "注意力經濟", "演算法推薦",
         "歷史終結", "柏納斯-李"},
        "009",
    ),
    # CAU-012 科技躍遷史 — acceleration curve / interval question
    (
        {"技術躍遷", "科技躍遷", "加速曲線", "下一次躍遷",
         "下一次大躍遷", "技術變革", "文明躍遷",
         "間隔", "越嚟越短", "速度倍增"},
        "012",
    ),
    # CAU-011 AI — already topic-expanded via _TOPIC_EXPANSIONS but also
    # add file-boost path for queries about alignment / RLHF / 對齊矛盾
    (
        {"AI", "人工智能", "ChatGPT", "GPT", "LLM",
         "RLHF", "alignment", "對齊", "湧現",
         "格式化工具", "認知依賴"},
        "011",
    ),
    # CAU-010 香港 2019 — physical anchor; only fire on EXPLICIT
    # geo+date markers to avoid bleed
    (
        {"香港 2019", "Hong Kong 2019", "Be Water", "金鐘", "六二一二",
         "612", "2019-06-12", "去中心化抗爭"},
        "010",
    ),
    # Older CAU files — keep conservative triggers (less common queries)
    (
        {"軸心時代", "axial age", "蘇美", "烏魯克", "Uruk"},
        "001",
    ),
    (
        {"書寫", "writing system", "象形", "甲骨", "蘇美刻字"},
        "002",
    ),
    (
        {"農業革命", "agricultural revolution", "新石器", "neolithic"},
        "004",
    ),
    (
        {"法國大革命", "French Revolution", "啟蒙運動", "Enlightenment",
         "Bastille"},
        "006",
    ),
    (
        {"工業革命", "Industrial Revolution", "蒸汽機", "steam engine",
         "瓦特", "Watt"},
        "007",
    ),
    (
        {"世界大戰", "World War", "核武器", "nuclear weapon",
         "冷戰", "Cold War"},
        "008",
    ),
]


# v8.30 p17 — per-CAU query vocab expansion. When a topic trigger fires
# for CAU-NNN, also expand the query with these file-specific tokens so
# that even chunks with sparse TF-IDF overlap get a meaningful base score
# (otherwise 4× boost on zero is still zero). Tokens chosen to maximise
# overlap with the file's deep sections without leaking out to unrelated
# files.
_CAU_VOCAB_EXPANSIONS = {
    "003": ["印刷機", "古騰堡", "1440", "1517", "路德", "95條",
            "宗教改革", "拉丁文", "教會", "壟斷", "傳播", "77年"],
    "005": ["黑死病", "鼠疫", "Yersinia", "1347", "1351", "教會",
            "格式化", "信仰", "崩潰", "Munro", "勞工法令", "農奴",
            "倖存者", "創傷"],
    "009": ["互聯網", "1991", "去中心化", "ARPANET", "Facebook",
            "iPhone", "監控資本主義", "注意力", "平台效應", "演算法",
            "推薦", "去中心化"],
    "010": ["香港", "2019", "Be Water", "去中心化", "金鐘"],
    "011": ["AI", "ChatGPT", "RLHF", "對齊", "alignment", "湧現",
            "格式化工具", "個性化", "認知依賴", "雙向格式化"],
    "012": ["技術躍遷", "加速曲線", "397", "154", "31", "2031",
            "Wonderwerk", "三層躍遷", "能量控制", "資訊傳播"],
    "001": ["軸心時代", "蘇美", "烏魯克", "公元前"],
    "002": ["書寫", "蘇美", "公元前3200", "象形"],
    "004": ["農業革命", "新石器", "1萬年"],
    "006": ["法國大革命", "1789", "啟蒙", "Bastille"],
    "007": ["工業革命", "蒸汽機", "瓦特", "1769", "煤炭"],
    "008": ["世界大戰", "核武器", "1945", "冷戰", "蘇聯"],
}


def _topic_inferred_cau_ids(query: str) -> set:
    """Detect CAU ids from natural-language topic vocabulary (no explicit
    CAU id required). Returns set of cau_id strings."""
    if not query:
        return set()
    q_lower = query.lower()
    hits: set = set()
    for trigger_set, cau_id in _TOPIC_TO_CAU_ID:
        for t in trigger_set:
            if _trigger_in_query(query, q_lower, t) or t in query:
                hits.add(cau_id)
                break
    return hits


def _all_cau_ids_for_query(query: str) -> set:
    """Union: explicit CAU-NNN ids + topic-inferred ids."""
    return _cau_ids_in_query(query) | _topic_inferred_cau_ids(query)


def _chunk_source_matches_cau_id(source_file: str, cau_id: str) -> bool:
    """True iff the source_file is the canonical CAU file for this id, e.g.
    `CAU-011_AI_EMERGENCE.md` or `11_AI_EMERGENCE.md` for cau_id='011'."""
    if not source_file:
        return False
    sf = source_file.replace("\\", "/")
    fname = sf.rsplit("/", 1)[-1]
    return (
        fname.startswith(f"CAU-{cau_id}_")
        or fname.startswith(f"{cau_id}_")
        or fname.startswith(f"CAU{cau_id}_")
    )


class RagRetriever:
    """In-memory TF-IDF retriever with sparse vectors."""

    def __init__(self, index_dir: Path = INDEX_DIR):
        self.index_dir = index_dir
        self.chunks: List[Dict] = []
        self.idf: Dict[str, float] = {}
        self.manifest: Dict = {}
        self.knowledge_docs: Dict[str, Dict] = {}
        self.loaded: bool = False
        self.load_error: Optional[str] = None
        self._load()

    # ─── loading ────────────────────────────────────────────
    def _load(self) -> None:
        try:
            manifest_path = self.index_dir / "manifest.json"
            chunks_path = self.index_dir / "chunks.jsonl"
            idf_path = self.index_dir / "idf.json"
            if not (manifest_path.exists() and chunks_path.exists() and idf_path.exists()):
                self.load_error = f"index files missing under {self.index_dir}"
                return
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.idf = json.loads(idf_path.read_text(encoding="utf-8"))
            chunks: List[Dict] = []
            with open(chunks_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    chunks.append(json.loads(line))
            self.chunks = chunks
            if documents_by_path is not None:
                try:
                    self.knowledge_docs = {
                        path: doc.to_dict(root=ROOT, include_hash=True)
                        for path, doc in documents_by_path(root=ROOT).items()
                    }
                except Exception:
                    self.knowledge_docs = {}
            self.loaded = True
        except Exception as e:
            self.load_error = f"{type(e).__name__}: {e}"

    # ─── query embedding (TF-IDF with v8.30 p8 topic expansion + p17 CAU vocab expansion) ───
    def _query_vec(self, query: str, expanded: bool = True) -> Dict[str, float]:
        q = _expand_query(query) if expanded else query
        # v8.30 p17 — when topic infers a CAU id, also append that CAU's
        # file-specific vocab so deep-section chunks get a nonzero base
        # TF-IDF score (boost alone is multiplicative — needs nonzero base).
        if expanded:
            inferred = _topic_inferred_cau_ids(query)
            extras: List[str] = []
            seen = set()
            for cid in inferred:
                for tok in _CAU_VOCAB_EXPANSIONS.get(cid, []):
                    if tok not in seen:
                        extras.append(tok)
                        seen.add(tok)
            if extras:
                q = q + "  " + " ".join(extras)
        toks = _tokenize(q)
        if not toks:
            return {}
        tf = Counter(toks)
        vec: Dict[str, float] = {}
        for t, freq in tf.items():
            idf_t = self.idf.get(t)
            if idf_t is None:
                continue
            vec[t] = (1.0 + math.log(freq)) * idf_t
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    @staticmethod
    def _topic_detected(query: str) -> bool:
        if not query:
            return False
        q_lower = query.lower()
        for trigger_set, _ in _TOPIC_EXPANSIONS:
            if any(_trigger_in_query(query, q_lower, t) for t in trigger_set):
                return True
        return False

    # ─── core retrieval ─────────────────────────────────────
    def retrieve(self, query: str, k: int = 5,
                 max_total_chars: int = 2500) -> List[Dict]:
        """Return top-k chunks with score, capped by total char budget.

        v8.30 p8 — when topic detected (civilization/history/etc), boost
        CAU/canonical source patterns 1.4× so substantive chunks rank above
        generic baseline references.
        """
        if not self.loaded:
            return []
        qv = self._query_vec(query)
        if not qv:
            return []
        topic_hit = self._topic_detected(query)
        kairos_date_hit = _kairos_date_query(query)
        # v8.30 p15 → p17: union explicit-id + topic-inferred ids so natural
        # queries (no "CAU-NNN" mention) still trigger the per-file boost.
        cau_ids = _all_cau_ids_for_query(query)
        scored: List = []
        for c in self.chunks:
            tfidf = c.get("tfidf", {})
            if not tfidf:
                continue
            score = 0.0
            for t, qv_t in qv.items():
                cv = tfidf.get(t)
                if cv is not None:
                    score += qv_t * cv
            src = c.get("source_file", "")
            # v8.30 p15 — per-CAU-id BIG boost so the substantive sections of
            # the referenced CAU file (e.g. ## 關鍵缺口識別 / ## 對當前協議的
            # 計算意義) climb above the index summary + base-參數 row.
            # Without this, TF-IDF alone returns only the 271-char base-参數
            # table and a 296-char index summary — the deep analysis never
            # reaches the LLM and CAU-011 citations end up as name-drops.
            cau_boost_applied = False
            if cau_ids:
                for cid in cau_ids:
                    if _chunk_source_matches_cau_id(src, cid):
                        score *= 4.0
                        cau_boost_applied = True
                        break
            if score > 0:
                # CAU / canonical-substance boost when topic detected
                # (still applies on top, but per-CAU boost is stronger
                # because it's surgical — only the asked file).
                if topic_hit and not cau_boost_applied:
                    if any(p in src for p in _CAU_SOURCE_PATTERNS):
                        score *= 1.4
                if kairos_date_hit and any(p in src for p in _KAIROS_ARCHIVE_SOURCE_PATTERNS):
                    score *= 2.2
                if kairos_date_hit and not any(p in src for p in _KAIROS_DATE_ALLOWED_SOURCE_PATTERNS):
                    score *= 0.25
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)

        out: List[Dict] = []
        total = 0
        # Consider extra candidates for char-budget packing
        for score, c in scored[: max(k * 3, k + 5)]:
            text = c["text"]
            if total + len(text) > max_total_chars and out:
                break
            item = {
                "id": c.get("id", ""),
                "source_file": c.get("source_file", ""),
                "section": c.get("section", ""),
                "text": text,
                "score": float(score),
            }
            knowledge_doc = self.knowledge_docs.get(item["source_file"])
            if knowledge_doc:
                item["doc_id"] = knowledge_doc.get("id")
                item["doc_layer"] = knowledge_doc.get("layer")
                item["doc_canonical"] = knowledge_doc.get("canonical")
                item["doc_sha256"] = knowledge_doc.get("sha256")
            out.append(item)
            total += len(text)
            if len(out) >= k:
                break
        return out

    # ─── prompt-ready formatter ─────────────────────────────
    def format_for_prompt(self, query: str, k: int = 5,
                          max_total_chars: int = 2500) -> str:
        """Format retrieved chunks as an injectable prompt block.

        Returns empty string when nothing relevant is found — callers can
        unconditionally concatenate without disturbing existing prompts.
        """
        results = self.retrieve(query, k=k, max_total_chars=max_total_chars)
        return self.format_results_for_prompt(results)

    def format_results_for_prompt(self, results: List[Dict]) -> str:
        """Format already-retrieved chunks without running retrieval twice."""
        if not results:
            return ""
        method = self.manifest.get("method", "tfidf")
        lines = [
            f"━━━ RAG retrieval — top {len(results)} for this query "
            f"(engine={method}) ━━━"
        ]
        for r in results:
            tag = r["source_file"].split("/")[-1]
            sect = r["section"]
            sect_disp = "" if sect in ("", "preamble") else sect[:80]
            head = f"--- [{tag}]" + (f" :: {sect_disp}" if sect_disp else "")
            head += f"   (score={r['score']:.3f})"
            lines.append(head)
            lines.append(r["text"])
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines) + "\n\n"


# ─────────────────────────────────────────────────────────────
# Module-level singleton — lazy, fail-silent
# ─────────────────────────────────────────────────────────────

_singleton: Optional[RagRetriever] = None
_singleton_attempted: bool = False


def get_retriever() -> Optional[RagRetriever]:
    """Return the loaded retriever, or None if unavailable.

    Never raises. Pipeline callers can `r = get_retriever()` and check.
    """
    global _singleton, _singleton_attempted
    if _singleton_attempted:
        return _singleton if (_singleton and _singleton.loaded) else None
    _singleton_attempted = True
    try:
        r = RagRetriever()
        _singleton = r if r.loaded else None
    except Exception:
        _singleton = None
    return _singleton


def reset_for_test() -> None:
    """Clear singleton state (used in unit tests)."""
    global _singleton, _singleton_attempted
    _singleton = None
    _singleton_attempted = False
