"""
URUK Trinity Console — RAG indexer (Phase 2 v1.0)

Builds a sparse TF-IDF index over the canonical reference corpus so that
query-time retrieval can surface the most relevant chunks instead of
preloading the whole corpus as static prompt context.

Engine selection
----------------
This v1 ships with **pure-numpy TF-IDF** as the primary engine.
`fastembed` was the original target but does not build on Python 3.14
(transitive `py-rust-stemmers` needs Rust toolchain). The TF-IDF path is
intentionally dep-light (numpy only) and supports CJK + Latin mixed text
via a per-character CJK tokenizer.

Storage layout
--------------
    data/rag_index/
      manifest.json     # method, model, built_at, source_hashes, n_chunks
      chunks.jsonl      # one chunk per line, includes pre-computed sparse TF-IDF
      idf.json          # {token: idf_score} global IDF table

CLI
---
    py services/rag_indexer.py --build
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).parent.parent
INDEX_DIR = ROOT / "data" / "rag_index"

# ─────────────────────────────────────────────────────────────
# Corpus selection
# ─────────────────────────────────────────────────────────────

def _collect_sources() -> List[Path]:
    """Enumerate the canonical reference corpus paths."""
    sources: List[Path] = [
        ROOT / "README.md",
        ROOT / "DESIGN_ANALYSIS.md",
        ROOT / "docs" / "README.md",
        ROOT / "docs" / "model-onboarding.md",
        ROOT / "docs" / "SEARCH_API_OPTIONS.md",
        ROOT / "config" / "README.md",
        ROOT / "data" / "README.md",
        ROOT / "services" / "README.md",
        ROOT / "static" / "README.md",
        ROOT / "tools" / "README.md",
        ROOT / "tests" / "README.md",
        ROOT / "skills" / "README.md",
        ROOT / "data" / "index" / "RAG_SUMMARY_INDEX_v8.md",
        ROOT / "data" / "index" / "CAU_INDEX.md",
        ROOT / "data" / "index" / "MASTER_INDEX_v8.md",
        ROOT / "data" / "index" / "URUK_README.md",
        ROOT / "data" / "index" / "CONSOLE_NAVIGATION.md",
        ROOT / "data" / "index" / "EXPERIMENT_INDEX.md",
        ROOT / "data" / "index" / "HARNESS_EPISODE_INDEX.md",
        ROOT / "data" / "index" / "UPGRADE_HISTORY_INDEX.md",
        ROOT / "data" / "core" / "KAIROS_CORE.md",
        ROOT / "data" / "core" / "PHYSICS_CONSTANTS.md",
        ROOT / "data" / "kairos" / "KAIROS_ACTIVE.md",
        ROOT / "data" / "kairos" / "KAIROS_ARCHIVE_INDEX.md",
    ]
    sources += [
        ROOT / "codex-relay-SKILL.md",
        ROOT / "codex-review-SKILL.md",
        ROOT / "codex-tool-designer-SKILL.md",
        ROOT / "codex-upgrade-SKILL.md",
        ROOT / "uruk-relay-SKILL.md",
        ROOT / "skills" / "blackbox-lab" / "SKILL.md",
        ROOT / "skills" / "kairos-density-audit" / "SKILL.md",
        ROOT / "skills" / "master-router" / "SKILL.md",
        ROOT / "skills" / "news-filter" / "SKILL.md",
        ROOT / "skills" / "scr-soul-reorg" / "SKILL.md",
        ROOT / "skills" / "trinity-audit" / "SKILL.md",
        ROOT / "skills" / "uruk-audit" / "SKILL.md",
        ROOT / "skills" / "uruk-learn" / "SKILL.md",
        ROOT / "skills" / "uruk-self-upgrade" / "SKILL.md",
        ROOT / "skills" / "uruk-sovereign-protocol" / "SKILL.md",
    ]
    sources += sorted((ROOT / "config" / "protocol" / "references").glob("*.md"))
    sources += sorted((ROOT / "config" / "protocol" / "references" / "module_t").glob("*.md"))
    sources += sorted((ROOT / "config" / "protocol" / "references" / "scr").rglob("*.md"))
    sources += sorted((ROOT / "data" / "scr_profiles").glob("*.md"))
    # v8.30 RAG-3: theory + protocol corpus (5 canonical docs + 8 protocol matrices).
    sources += sorted((ROOT / "data" / "theory").glob("*.md"))
    sources += sorted((ROOT / "data" / "misc").glob("*.md"))
    sources += sorted((ROOT / "data" / "protocol").glob("*.md"))
    # v8.30 p8: rich CAU substance — 12 individual CAU-001..012.md files.
    # Previously RAG only had the short CAU summaries in RAG_SUMMARY_INDEX_v8.md;
    # the detailed timelines / ratios / mechanism breakdowns lived in
    # data/causal_db/ which was outside the corpus → "civilization" queries
    # could only name-drop CAU IDs without quoting substantive data.
    sources += sorted((ROOT / "data" / "causal_db").glob("*.md"))
    sources += sorted((ROOT / "data" / "causal_records").glob("*.md"))
    seen = set()
    deduped = []
    for p in sources:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        deduped.append(p)
    return deduped


# ─────────────────────────────────────────────────────────────
# Tokenisation — multilingual (Latin word OR single CJK char)
# ─────────────────────────────────────────────────────────────

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]*|\d{1,4}|[一-鿿]|[぀-ヿ]")


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


# ─────────────────────────────────────────────────────────────
# Section-aware chunking — split on ## / ### then recursive overlap
# ─────────────────────────────────────────────────────────────

CHUNK_MAX_CHARS = 700
CHUNK_OVERLAP = 150
HEADING_RE = re.compile(r"^#{2,4}\s+", re.MULTILINE)


def section_split(text: str) -> List[Tuple[str, str]]:
    """Split markdown by ## / ### / #### headings.

    Returns [(heading_line, body_text), ...].
    Pre-heading content is grouped under 'preamble'.
    """
    lines = text.split("\n")
    chunks: List[Tuple[str, str]] = []
    cur_heading = "preamble"
    cur_body: List[str] = []
    for line in lines:
        if HEADING_RE.match(line):
            if cur_body:
                body = "\n".join(cur_body).strip()
                if body:
                    chunks.append((cur_heading, body))
            cur_heading = line.strip()
            cur_body = []
        else:
            cur_body.append(line)
    if cur_body:
        body = "\n".join(cur_body).strip()
        if body:
            chunks.append((cur_heading, body))
    return chunks


def recursive_split(text: str,
                    max_chars: int = CHUNK_MAX_CHARS,
                    overlap: int = CHUNK_OVERLAP) -> List[str]:
    """If text <= max_chars, return as-is. Else split with sliding window."""
    if len(text) <= max_chars:
        return [text]
    out: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        # Try to break at paragraph boundary if there's one near `end`
        if end < len(text):
            nl = text.rfind("\n\n", start + max_chars // 2, end)
            if nl > 0:
                end = nl
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [x for x in out if x]


def chunk_file(path: Path) -> List[Dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    out: List[Dict] = []
    for heading, body in section_split(text):
        for sub in recursive_split(body):
            out.append({
                "source_file": rel,
                "section": heading,
                "text": sub,
            })
    return out


# ─────────────────────────────────────────────────────────────
# TF-IDF — sparse per-chunk, L2-normalised
# ─────────────────────────────────────────────────────────────

def compute_tfidf(chunks: List[Dict]) -> Dict[str, float]:
    """Add 'tfidf' field to each chunk (dict[token, weight]).

    Returns the global IDF table.
    """
    N = len(chunks)
    df: Counter[str] = Counter()
    chunk_tokens: List[List[str]] = []
    for c in chunks:
        toks = tokenize(c["text"])
        chunk_tokens.append(toks)
        for t in set(toks):
            df[t] += 1
    idf: Dict[str, float] = {
        t: math.log((1.0 + N) / (1.0 + d)) + 1.0
        for t, d in df.items()
    }
    for c, toks in zip(chunks, chunk_tokens):
        if not toks:
            c["tfidf"] = {}
            continue
        tf = Counter(toks)
        vec: Dict[str, float] = {}
        for t, freq in tf.items():
            idf_t = idf.get(t)
            if idf_t is None:
                continue
            vec[t] = (1.0 + math.log(freq)) * idf_t
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        c["tfidf"] = {t: v / norm for t, v in vec.items()}
    return idf


# ─────────────────────────────────────────────────────────────
# Index build + persist
# ─────────────────────────────────────────────────────────────

def build_index(verbose: bool = True) -> Dict:
    sources = _collect_sources()
    all_chunks: List[Dict] = []
    source_hashes: Dict[str, str] = {}
    for src in sources:
        if not src.exists():
            if verbose:
                print(f"  SKIP {src} (not found)")
            continue
        text = src.read_text(encoding="utf-8", errors="replace")
        rel = str(src.relative_to(ROOT)).replace("\\", "/")
        source_hashes[rel] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        chunks = chunk_file(src)
        for i, c in enumerate(chunks):
            c["id"] = f"{src.stem}__{i:03d}"
        all_chunks.extend(chunks)
        if verbose:
            print(f"  + {rel}: {len(chunks)} chunks")
    if verbose:
        print(f"Computing TF-IDF over {len(all_chunks)} chunks ...")
    idf = compute_tfidf(all_chunks)
    return {
        "chunks": all_chunks,
        "idf": idf,
        "n_chunks": len(all_chunks),
        "vocab_size": len(idf),
        "source_hashes": source_hashes,
    }


def save_index(index: Dict, out_dir: Path = INDEX_DIR) -> Dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in index["chunks"]:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(out_dir / "idf.json", "w", encoding="utf-8") as f:
        json.dump(index["idf"], f, ensure_ascii=False)
    manifest = {
        "method": "tfidf",
        "model": "tfidf-multilingual-char-word",
        "engine_fallback_reason": (
            "fastembed install failed on Python 3.14 — py-rust-stemmers "
            "needs Rust toolchain; auto-fellback to pure-numpy TF-IDF"
        ),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "n_chunks": index["n_chunks"],
        "vocab_size": index["vocab_size"],
        "chunk_max_chars": CHUNK_MAX_CHARS,
        "chunk_overlap": CHUNK_OVERLAP,
        "source_hashes": index["source_hashes"],
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="URUK RAG indexer")
    parser.add_argument("--build", action="store_true", help="Build the RAG index")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-file logging")
    args = parser.parse_args(argv)
    if not args.build:
        parser.print_help()
        return 1
    print(f"URUK RAG indexer — building index in {INDEX_DIR}")
    idx = build_index(verbose=not args.quiet)
    mf = save_index(idx)
    print(f"Done: {mf['n_chunks']} chunks, vocab={mf['vocab_size']}, "
          f"sources={len(mf['source_hashes'])}, method={mf['method']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
