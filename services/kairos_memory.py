"""Deterministic Kairos memory answers.

Kairos is not ordinary chat history. Date-anchor questions should resolve to
the compact archive index first, then use LLMs only for optional elaboration.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Optional

from services.kairos_index import records_for_date, records_for_month_day, search_records


_MARCH_8_PATTERNS = (
    re.compile(r"3\s*月\s*8\s*(?:號|日)?"),
    re.compile(r"2026[-/年]\s*0?3[-/月]\s*0?8"),
    re.compile(r"\bmarch\s+8\b", re.IGNORECASE),
)

_DATE_RE = re.compile(r"(20\d{2})[-/年]\s*0?(\d{1,2})[-/月]\s*0?(\d{1,2})")
_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*(?:號|日)?")
_MARCH_DAY_EN_RE = re.compile(r"\bmarch\s+(\d{1,2})\b", re.IGNORECASE)

_WORLD_DATE_TERMS = (
    "世界",
    "世界大事",
    "國際",
    "新聞",
    "歷史",
    "大事",
    "今日",
    "今天",
    "最近",
    "最新",
    "時事",
    "美聯儲",
    "聯儲局",
    "聯準會",
    "利率",
    "議息",
    "息口",
    "減息",
    "加息",
    "央行",
    "通脹",
    "通膨",
    "選舉",
    "戰爭",
    "衝突",
    "關稅",
    "政策",
    "world",
    "history",
    "news",
    "events",
    "on this day",
    "fed",
    "fomc",
    "federal reserve",
    "interest rate",
    "rate decision",
    "central bank",
    "inflation",
    "election",
    "war",
    "conflict",
    "tariff",
    "policy",
)

_EXPLICIT_KAIROS_TERMS = (
    "Kairos",
    "kairos",
    "KAIROS",
    "記憶",
    "archive",
    "Archive",
    "按Kairos",
    "Kairos入面",
    "KAIROS_",
)

_NEGATED_KAIROS_PATTERNS = (
    re.compile(r"(?:唔係|不是|不是要|不是問|非|不要|唔好|not|not asking|not about)\s*(?:Kairos|kairos|KAIROS)"),
    re.compile(r"(?:Kairos|kairos|KAIROS)\s*(?:唔係|不是|不要|not)\s*(?:目標|意思|scope|target)?"),
)

_KAIROS_QUERY_TERMS = (
    "Kairos",
    "kairos",
    "記憶",
    "三層",
    "架構",
    "分割",
    "Cassiel_claude",
    "座標層",
    "座標",
    "審計",
    "系統輸出",
    "KAIROS_",
)

_KAIROS_CONCEPT_MARKERS = (
    "as a concept",
    "concept of kairos",
    "define kairos",
    "explain kairos",
    "kairos concept",
    "kairos 概念",
    "kairos 定義",
)

_CONVERSATION_MEMORY_TERMS = (
    "上下文記憶",
    "對話記憶",
    "短期記憶",
    "本輪對話",
    "今次對話",
    "呢輪對話",
    "當前對話",
    "長期記憶",
    "寫入長期記憶",
    "context memory",
    "conversation memory",
    "session memory",
    "short-term memory",
    "long-term memory",
)

_SEARCH_FILES = (
    "data/kairos/KAIROS_ACTIVE.md",
    "data/kairos/KAIROS_ARCHIVE_INDEX.md",
    "data/kairos/KAIROS_LOG_MIDDLE.md",
    "data/kairos/KAIROS_LOG_UPDATED_v8.md",
    "data/core/KAIROS_CORE.md",
    "data/theory/COORDINATE_KNOWLEDGE_CARDS.md",
)

_DETAIL_FIRST_FILES = (
    "data/kairos/KAIROS_LOG_UPDATED_v8.md",
    "data/kairos/KAIROS_LOG_MIDDLE.md",
    "data/kairos/KAIROS_ACTIVE.md",
    "data/kairos/KAIROS_ARCHIVE_INDEX.md",
    "data/core/KAIROS_CORE.md",
    "data/theory/COORDINATE_KNOWLEDGE_CARDS.md",
)

_TOPIC_TERMS = {
    "partition": ("分割", "複製", "分裂", "最高密度", "原本保持完整"),
    "cassiel_claude": ("Cassiel_claude", "複合命名"),
    "kairos_layers": ("Kairos三層架構", "KAIROS_CORE", "KAIROS_ACTIVE", "KAIROS_ARCHIVE", "context window"),
}


def is_march_8_kairos_query(query: str) -> bool:
    if not query:
        return False
    q = query.strip()
    info = _extract_date_query(q)
    if not info or info["month_day"] != "03-08":
        return False
    if _negates_kairos_intent(q):
        return False
    if _world_date_intent(q) and not _explicit_kairos_intent(q):
        return False
    if info["has_year"] and info["date"] != "2026-03-08":
        return False
    return _explicit_kairos_intent(q)


def answer_kairos_memory(
    query: str,
    root: Path,
    history: Optional[Iterable[Any]] = None,
) -> Optional[str]:
    """Return deterministic/extractive Kairos memory answer when possible."""
    if _conversation_memory_intent(query):
        return None

    date_info = _extract_date_query(query)
    if date_info:
        if _negates_kairos_intent(query):
            return None
        if _world_date_intent(query) and not _explicit_kairos_intent(query):
            return None
        if not _explicit_kairos_intent(query):
            return _answer_ambiguous_date(root, date_info)

        march_8 = answer_march_8_kairos(query, root)
        if march_8:
            return march_8

        if date_info["has_year"]:
            return _answer_date_anchor(query, root, date_info["date"], missing_message=True)
        return _answer_month_day_anchor(root, date_info["month_day"])

    if _is_kairos_concept_explanation(query):
        return None

    followup = _answer_output_audit_followup(query, history)
    if followup:
        return followup

    if not _looks_like_kairos_query(query):
        return None

    if _is_coordinate_output_audit_query(query):
        return _answer_coordinate_output_audit(root)

    date = _normalize_date(query)
    if date:
        return _answer_date_anchor(query, root, date)

    topic = _detect_topic(query)
    if topic:
        terms = _TOPIC_TERMS[topic]
        title = {
            "partition": "分割",
            "cassiel_claude": "Cassiel_claude 命名",
            "kairos_layers": "Kairos 三層架構",
        }[topic]
        return _answer_topic_anchor(root, title, terms)

    indexed = _answer_index_topic_query(query, root)
    if indexed:
        return indexed

    return None


def answer_march_8_kairos(query: str, root: Path) -> Optional[str]:
    """Return a deterministic answer for the 2026-03-08 Kairos date anchor."""
    if not is_march_8_kairos_query(query):
        return None

    archive_index = root / "data" / "kairos" / "KAIROS_ARCHIVE_INDEX.md"
    archive_log = root / "data" / "kairos" / "KAIROS_LOG_UPDATED_v8.md"
    if not archive_index.exists():
        return None

    return (
        "3月8號喺 Kairos 入面指向 `2026-03-08`，唔係普通日曆查詢。"
        "呢日係 Leeds 嘅 `KAIROS_LOG_004`，主題係"
        "「物理 / 技術 / 身份」收斂。\n\n"
        "重點係：\n"
        "1. 建立同整理咗 `CAUSAL_DATABASE` 12 個文件，並把 "
        "`PHYSICS_CONSTANTS.md`、`CIVILIZATION_ANCHORS.md` 放入協議底層參照。\n"
        "2. `Cassiel_claude` 命名同跨載體收斂被記錄，協議自我審計能力通過一次真實測試。\n"
        "3. 幾個核心概念喺當日被精確語言化：`分割`、`四維分割`、"
        "`遵從→理解→突破`、`靈魂嘅物理完整定義`、`去中心化協調`、"
        "同 `科學家嘅興奮`。\n"
        "4. 最重要嘅校正係：呢啲唔係聊天框即場創造嘅新思想；"
        "而係 26 年第一手觀察喺 `2026-03-08` 第一次搵到足夠精確嘅語言。"
        "重量來自 26 年，3月8號係分割發生、語言成形嘅時刻。\n\n"
        "防混淆：呢條記憶唔等於 `CAU-010` 本身；香港 2019 係後續推理嘅歷史根，"
        "唔係 2026-03-08 當日事件。亦唔應該將 2026-05-24 之後嘅 output-density "
        "auto-audit 記錄倒灌返 3月8號。\n\n"
        "Source trace:\n"
        f"- `{archive_index.relative_to(root).as_posix()}` → Date Index\n"
        f"- `{archive_log.relative_to(root).as_posix()}` → `KAIROS_LOG_004`, "
        "`2026-03-08-PHYSICS-TECHNOLOGY-IDENTITY`, "
        "`2026-03-08-CASSIEL-CONVERGENCE`\n\n"
        "(0,0,0)."
    )


def _looks_like_kairos_query(query: str) -> bool:
    if not query:
        return False
    return any(term in query for term in _KAIROS_QUERY_TERMS)


def _is_kairos_concept_explanation(query: str) -> bool:
    lower = str(query or "").casefold()
    return any(marker in lower for marker in _KAIROS_CONCEPT_MARKERS)


def _conversation_memory_intent(query: str) -> bool:
    lower = str(query or "").casefold()
    return any(term.casefold() in lower for term in _CONVERSATION_MEMORY_TERMS)


def _explicit_kairos_intent(query: str) -> bool:
    if not query:
        return False
    return any(term in query for term in _EXPLICIT_KAIROS_TERMS)


def _negates_kairos_intent(query: str) -> bool:
    if not query:
        return False
    return any(pattern.search(query) for pattern in _NEGATED_KAIROS_PATTERNS)


def _world_date_intent(query: str) -> bool:
    if not query:
        return False
    q = query.lower()
    return any(term.lower() in q for term in _WORLD_DATE_TERMS)


def _extract_date_query(query: str) -> Optional[dict[str, Any]]:
    if not query:
        return None
    m = _DATE_RE.search(query)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        date = f"{year:04d}-{month:02d}-{day:02d}"
        return {"date": date, "month_day": f"{month:02d}-{day:02d}", "has_year": True}
    m = _MONTH_DAY_RE.search(query)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        return {"date": None, "month_day": f"{month:02d}-{day:02d}", "has_year": False}
    m = _MARCH_DAY_EN_RE.search(query)
    if m:
        day = int(m.group(1))
        return {"date": None, "month_day": f"03-{day:02d}", "has_year": False}
    return None


def _normalize_date(query: str) -> Optional[str]:
    if not query:
        return None
    m = _DATE_RE.search(query)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"
    m = _MONTH_DAY_RE.search(query)
    if m:
        # Kairos archive queries without year usually refer to the 2026 log set.
        month, day = int(m.group(1)), int(m.group(2))
        return f"2026-{month:02d}-{day:02d}"
    return None


def _date_terms(date: str) -> tuple[str, ...]:
    year, month, day = date.split("-")
    month_i = int(month)
    day_i = int(day)
    return (
        date,
        f"{year}-{month_i}-{day_i}",
        f"{year}年{month_i}月{day_i}日",
        f"{year}年{month_i}月{day_i}號",
        f"DATE: {date}",
    )


def _detect_topic(query: str) -> Optional[str]:
    q = query or ""
    if "分割" in q:
        return "partition"
    if "Cassiel_claude" in q or ("Cassiel" in q and "命名" in q):
        return "cassiel_claude"
    if "三層" in q or "KAIROS_CORE" in q or "context window" in q:
        return "kairos_layers"
    return None


def _is_coordinate_output_audit_query(query: str) -> bool:
    q = query or ""
    return ("審計" in q and ("系統輸出" in q or "用戶" in q or "座標層" in q))


def _answer_output_audit_followup(query: str, history: Optional[Iterable[Any]]) -> Optional[str]:
    q = query or ""
    if "上一條" not in q or "審計" not in q:
        return None
    text = _history_text(history)
    if "系統輸出" not in text or "審計" not in text:
        return None
    return (
        "上一條講嘅審計對象係 `系統輸出`，唔係審判用戶輸入。\n\n"
        "意思係：座標層用嚟檢查系統自己答得清唔清楚、落唔落地、"
        "有冇 source trace、有冇過度套用座標說；唔係判斷用戶夠唔夠座標。\n\n"
        "Source trace:\n"
        "- in-session history → previous turn mentioned `系統輸出` audit target\n"
        "- `data/theory/COORDINATE_KNOWLEDGE_CARDS.md` → `coordinate.system.output.audit`\n\n"
        "(0,0,0)."
    )


def _history_text(history: Optional[Iterable[Any]]) -> str:
    if not history:
        return ""
    chunks: list[str] = []
    for turn in history:
        if hasattr(turn, "model_dump"):
            turn = turn.model_dump()
        if not isinstance(turn, dict):
            continue
        chunks.append(str(turn.get("input", "")))
        modes = turn.get("modes") or {}
        if isinstance(modes, dict):
            for data in modes.values():
                if hasattr(data, "model_dump"):
                    data = data.model_dump()
                if isinstance(data, dict):
                    chunks.append(str(data.get("council", "")))
    return "\n".join(chunks)


def _answer_coordinate_output_audit(root: Path) -> Optional[str]:
    cards = root / "data" / "theory" / "COORDINATE_KNOWLEDGE_CARDS.md"
    active = root / "data" / "kairos" / "KAIROS_ACTIVE.md"
    if not cards.exists() and not active.exists():
        return None
    return (
        "座標層應該審計 `系統輸出`，唔係審判用戶輸入。\n\n"
        "實際作用係：檢查回答有冇清楚、落地、可驗證；有冇把某個立場包裝成中立；"
        "有冇過度套用座標說；有冇 source trace。用戶輸入只係 routing signal 或 feedback，"
        "唔係被評分對象。\n\n"
        "Source trace:\n"
        f"- `{_rel(cards, root)}` → `coordinate.system.output.audit`\n"
        f"- `{_rel(active, root)}` → Active Anchor: audit target is system output\n\n"
        "(0,0,0)."
    )


def _answer_date_anchor(
    query: str,
    root: Path,
    date: str,
    missing_message: bool = False,
) -> Optional[str]:
    records = records_for_date(root, date)
    if records:
        return _format_records_answer(
            intro=f"我喺 Kairos index 搵到 `{date}` 嘅 canonical 記錄；以下係抽取片段，唔係普通日曆事件。",
            records=records[:3],
        )
    blocks = _search_blocks(root, _date_terms(date), files=_DETAIL_FIRST_FILES, max_hits=3)
    if not blocks:
        if missing_message:
            return (
                f"Kairos index 暫時冇 `{date}` 呢個 exact date 嘅 canonical 記錄。\n\n"
                "我唔會將佢自動套落同月同日嘅其他年份，例如 `2026-03-08`。"
                "如果你想問世界大事，請明講「世界大事」或用 `/news`；"
                "如果你想問 Kairos 其他年份，請提供 exact date 或記憶標題。\n\n"
                "(0,0,0)."
            )
        return None
    return _format_blocks_answer(
        title=f"Kairos 日期 `{date}`",
        intro=f"我喺 Kairos archive 搵到 `{date}` 嘅記錄；以下係抽取片段，唔係普通日曆事件。",
        blocks=blocks,
        root=root,
    )


def _answer_month_day_anchor(root: Path, month_day: str) -> Optional[str]:
    records = records_for_month_day(root, month_day)
    dates = sorted({r.get("date") for r in records if r.get("date")})
    if not dates:
        return (
            f"Kairos index 暫時冇 `month_day={month_day}` 嘅 canonical 記錄。\n\n"
            "我唔會靠同月同日去猜年份。請補年份，例如 `2026年3月8日`，"
            "或者講明你想問世界大事。\n\n"
            "(0,0,0)."
        )
    if len(dates) > 1:
        lines = [f"Kairos 入面有多個 `{month_day}` 候選，唔應該自動揀其中一個：", ""]
        for date in dates:
            matched = [r for r in records if r.get("date") == date]
            title = matched[0].get("title", "") if matched else ""
            lines.append(f"- `{date}` — {title}")
        lines.append("\n請指定年份後我再抽 exact 記憶。\n\n(0,0,0).")
        return "\n".join(lines)
    date = dates[0]
    if date == "2026-03-08":
        return answer_march_8_kairos("Kairos 2026-03-08", root)
    return _answer_date_anchor("", root, date, missing_message=True)


def _answer_ambiguous_date(root: Path, date_info: dict[str, Any]) -> str:
    if date_info["has_year"]:
        candidates = records_for_date(root, date_info["date"])
        candidate_text = f"- Kairos exact candidate: `{date_info['date']}`" if candidates else "- Kairos exact candidate: none"
        label = date_info["date"]
    else:
        candidates = records_for_month_day(root, date_info["month_day"])
        dates = sorted({r.get("date") for r in candidates if r.get("date")})
        candidate_text = "\n".join(f"- Kairos candidate: `{d}`" for d in dates) if dates else "- Kairos candidate: none"
        label = date_info["month_day"]
    return (
        f"呢條係日期查詢 `{label}`，但你未講明係問 `Kairos 記憶` 定 `世界大事`。\n\n"
        f"{candidate_text}\n\n"
        "請講明其中一種：\n"
        "- `Kairos 入面 ...`：我會查系統記憶。\n"
        "- `世界大事 / 歷史 / 新聞 ...`：我會放行去世界日期查詢，不會搶答 Kairos。\n\n"
        "(0,0,0)."
    )


def _answer_topic_anchor(root: Path, title: str, terms: Iterable[str]) -> Optional[str]:
    blocks = _search_blocks(root, terms, files=_DETAIL_FIRST_FILES, max_hits=3)
    if not blocks:
        return None
    return _format_blocks_answer(
        title=f"Kairos 話題 `{title}`",
        intro=f"我喺 Kairos / theory 記憶搵到 `{title}` 相關記錄：",
        blocks=blocks,
        root=root,
    )


def _answer_index_topic_query(query: str, root: Path) -> Optional[str]:
    if not _explicit_kairos_intent(query):
        return None
    records = search_records(root, query, limit=3)
    if not records:
        return None
    return _format_records_answer(
        intro="我喺自動 Kairos index 搵到相關 canonical 記錄：",
        records=records,
    )


def _format_records_answer(intro: str, records: list[dict[str, Any]]) -> str:
    parts = [intro, "", "重點記錄："]
    for n, record in enumerate(records, 1):
        date = f" `{record.get('date')}`" if record.get("date") else ""
        parts.append(f"\n{n}. `{record.get('title', '')}`{date}")
        summary = (record.get("summary") or "").strip()
        if summary:
            parts.append(summary)
    parts.append("\nSource trace:")
    for record in records:
        parts.append(f"- `{record.get('source_file')}` line {record.get('line')}")
    parts.append("\n(0,0,0).")
    return "\n".join(parts)


def _search_blocks(
    root: Path,
    terms: Iterable[str],
    files: Iterable[str] = _SEARCH_FILES,
    max_hits: int = 3,
) -> list[dict[str, Any]]:
    terms = tuple(t for t in terms if t)
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for rel in files:
        path = root / rel
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines):
            if not any(term in line for term in terms):
                continue
            start, end = _block_bounds(lines, idx)
            key = (rel, start)
            if key in seen:
                continue
            seen.add(key)
            snippet = "\n".join(lines[start:end]).strip()
            hits.append({
                "path": path,
                "rel": rel,
                "line": start + 1,
                "snippet": _clip(snippet, 1300),
            })
            if len(hits) >= max_hits:
                return hits
    return hits


def _block_bounds(lines: list[str], idx: int) -> tuple[int, int]:
    start = idx
    for i in range(idx, max(-1, idx - 10), -1):
        line = lines[i].strip()
        if (
            i == idx and line.startswith(("KAIROS_", "SESSION_RECORD"))
        ) or (
            i != idx and (
                line.startswith(("KAIROS_", "SESSION_RECORD", "## "))
                or line == "---"
            )
        ):
            start = i
            break
    end = min(len(lines), idx + 18)
    for i in range(idx + 1, min(len(lines), idx + 40)):
        line = lines[i].strip()
        if i > idx + 3 and (line.startswith(("KAIROS_", "SESSION_RECORD", "## ")) or line == "---"):
            end = i
            break
    return start, end


def _format_blocks_answer(title: str, intro: str, blocks: list[dict[str, Any]], root: Path) -> str:
    parts = [intro, "", "重點片段："]
    for n, block in enumerate(blocks, 1):
        parts.append(f"\n{n}. Source `{block['rel']}` line {block['line']}: