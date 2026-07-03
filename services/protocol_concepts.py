"""Protocol-level abstract concept detection.

Short concept questions are cheap to misroute: "what is freedom?" looks like
ordinary Q&A, but inside URUK it should pass through Coordinate/Trinity instead
of the small/simple answer path.  This helper keeps that policy consistent
across the cost router, pre-gate, smart router, and small-task guard.
"""

from __future__ import annotations

import re


PROTOCOL_CONCEPT_TERMS = (
    "自由",
    "自由度",
    "愛",
    "恐懼",
    "勇氣",
    "希望",
    "信任",
    "背叛",
    "真理",
    "真假",
    "謊言",
    "正義",
    "公義",
    "公平",
    "道德",
    "倫理",
    "善惡",
    "尊嚴",
    "權力",
    "權利",
    "主權",
    "自治",
    "民主",
    "文明",
    "秩序",
    "混亂",
    "責任",
    "義務",
    "代價",
    "選擇",
    "意義",
    "價值",
    "存在",
    "虛無",
    "生命",
    "死亡",
    "時間",
    "記憶",
    "歷史",
    "身份",
    "自我",
    "人格",
    "意識",
    "靈魂",
    "信仰",
    "宗教",
    "美",
    "安全",
    "和平",
    "暴力",
    "服從",
    "反抗",
    "格式化",
    "座標",
    "坐標",
    "可能性空間",
    "熵",
    "負熵",
    "freedom",
    "liberty",
    "freedom_loss",
    "freedom_loss_entropy",
    "lie_cost",
    "landauer",
    "love",
    "fear",
    "courage",
    "hope",
    "trust",
    "truth",
    "lie",
    "justice",
    "fairness",
    "ethics",
    "morality",
    "dignity",
    "power",
    "rights",
    "sovereignty",
    "autonomy",
    "democracy",
    "civilization",
    "order",
    "chaos",
    "responsibility",
    "choice",
    "meaning",
    "value",
    "existence",
    "nihilism",
    "life",
    "death",
    "time",
    "memory",
    "history",
    "identity",
    "self",
    "consciousness",
    "soul",
    "faith",
    "religion",
    "beauty",
    "peace",
    "violence",
    "obedience",
    "resistance",
    "formatting",
    "entropy",
    "negentropy",
    "abstract concept",
)

_ABSTRACT_DEFINITION_MARKERS = (
    "咩係",
    "乜係",
    "咩叫",
    "乜叫",
    "什麼是",
    "甚麼是",
    "什么是",
    "何謂",
    "何为",
    "點定義",
    "如何定義",
    "定義一下",
    "解釋一下",
    "講下",
    "what is ",
    "what's ",
    "define ",
    "definition of ",
    "meaning of ",
)

_ORDINARY_FACTUAL_GUARDS = (
    "2+2",
    "capital",
    "首都",
    "人口",
    "weather",
    "天氣",
    "how many",
    "幾多",
    "when did",
    "幾時",
    "latest",
    "recent",
    "news",
    "price",
    "股價",
    "匯率",
    "version",
    "api",
    "python",
    "javascript",
    "typescript",
    "file",
    "folder",
    "screenshot",
    "code",
    "bug",
    "error",
    "http://",
    "https://",
    "alphabetical order",
    "title case",
    "lowercase",
    "uppercase",
    "comma-separated values",
    "comma separated values",
    "translate ",
    "convert ",
    "rewrite ",
    "calculate ",
)


def contains_protocol_concept(text: str) -> bool:
    lower = str(text or "").casefold()
    for term in PROTOCOL_CONCEPT_TERMS:
        needle = term.casefold()
        if not needle:
            continue
        if re.fullmatch(r"[a-z][a-z0-9_ -]*", needle):
            if re.search(rf"(?<![a-z0-9_]){re.escape(needle)}(?![a-z0-9_])", lower):
                return True
            continue
        if needle in lower:
            return True
    return False


def is_protocol_concept_query(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    lower = raw.casefold()
    if any(guard in lower for guard in _ORDINARY_FACTUAL_GUARDS):
        return False
    if contains_protocol_concept(lower):
        return True
    if not any(marker in lower for marker in _ABSTRACT_DEFINITION_MARKERS):
        return False
    if re.search(r"\d", raw):
        return False
    if re.search(r"[{}<>]|==|/api|\.py\b|\.js\b", lower):
        return False

    # Short Chinese "咩係 X" / "何謂 X" questions are usually concept
    # definitions. Route them through protocol unless a factual guard matched.
    has_cjk = re.search(r"[\u4e00-\u9fff]", raw) is not None
    if has_cjk and len(raw) <= 80:
        return True

    # For English, keep the generic marker conservative and rely on the concept
    # lexicon above. This avoids routing "what is Paris?" as protocol work.
    return False
