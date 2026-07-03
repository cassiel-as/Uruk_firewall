"""
URUK Pre-Gate Dispatcher — v1.0
在 Stage 1 之前做一次輕量分類 call，決定是否需要完整 Trinity pipeline。

分類結果：
  simple   → plain_llm (1 call, 省 97% cost)
  tool     → agent_chat (Planner-Executor)
  search   → /news BrowserNode
  complex  → 完整 pipeline (Stage 1-3 + Trinity)

設計原則：
  - 永遠只用最便宜嘅 model（GPT-4o-mini / Ollama qwen2.5:3b）
  - 輸出 structured JSON，唔係自然語言
  - Timeout 2 秒，超時就 fallback 到 complex（唔中斷 pipeline）
  - 偵測到 Uruk keywords 直接 → complex（唔做分類）
"""

from __future__ import annotations

import json
import os
import re
from typing import Literal

from services.protocol_concepts import is_protocol_concept_query

# ── Uruk keywords 直接繞過 pre-gate → complex ─────────────────────
_FORCE_COMPLEX = frozenset({
    "uruk", "firewall", "blackbox", "trinity", "kairos",
    "八律", "座標", "主權", "三位一體", "聖父", "聖子", "聖靈",
    "sovereign", "/scr", "/news", "/blackbox", "/firewall",
    "lie_cost", "freedom_loss", "freedom_loss_entropy",
    "自由", "自由度", "freedom", "liberty", "民主", "文明",
    "主權", "自治", "尊嚴", "存在", "意義", "真理", "價值",
    "靈魂", "抽象概念", "abstract concept", "(0,0,0)", "假設逆轉",
})

# ── Simple query signals ───────────────────────────────────────────
_SIMPLE_SIGNALS = frozenset({
    "係咩", "是什麼", "what is", "what's", "咩係",
    "點解", "why is", "幾多", "how many", "when did",
    "translate", "翻譯", "define", "definition",
    "hello", "你好", "hi ",
})

_TOOL_SIGNALS = frozenset({
    "截圖", "截取屏幕", "screenshot", "打開", "open",
    "讀取文件", "read file", "寫入", "write to",
    "click", "點擊", "type ", "輸入文字",
    "幫我做", "help me do", "execute", "run ",
    "控制", "control", "automate",
})

_SEARCH_SIGNALS = frozenset({
    "新聞", "news", "最新", "latest", "recent",
    "search", "搜索", "find out", "check online",
    "today", "今日", "現在發生", "happening",
})

PRE_GATE_SYSTEM = """\
你係一個輸入分類器。輸出 JSON，唔好有其他文字。

分類規則：
- simple:  簡單定義、翻譯、單一事實問題（唔需要深度推理）
- tool:    需要控制電腦、讀寫文件、截圖、自動化操作
- search:  需要搜尋最新資訊、新聞、實時數據
- complex: 需要哲學分析、多角度推理、深度評估、策略判斷

輸出格式（只輸出 JSON）：
{"type": "simple"|"tool"|"search"|"complex", "reason": "一句話解釋", "confidence": 0.0-1.0}
"""


_FORCE_COMPLEX = _FORCE_COMPLEX | frozenset({
    "座標說", "三位一體", "抽象概念", "自由", "熵", "靈魂", "主權",
})
_SIMPLE_SIGNALS = _SIMPLE_SIGNALS | frozenset({
    "係邊度", "係幾多", "有幾多", "翻譯", "簡單回答", "一句回答",
})
_TOOL_SIGNALS = _TOOL_SIGNALS | frozenset({
    "開啟", "打開", "截圖", "讀取檔案", "寫入檔案", "執行指令", "控制電腦",
})
_SEARCH_SIGNALS = _SEARCH_SIGNALS | frozenset({
    "最新", "今日", "而家", "新聞", "上網搜尋", "世界大事",
})
_COMPLEX_SIGNALS = frozenset({
    "分析", "比較", "評估", "風險", "因果", "策略", "設計", "架構", "點解",
    "analysis", "compare", "evaluate", "risk", "causal", "strategy", "architecture",
})

# Clean bounded prompt used by the local classifier.
PRE_GATE_SYSTEM = """\
You are URUK's bounded request classifier. Return JSON only.

Labels:
- simple: stable factual question, translation, formatting, or short low-risk answer
- tool: asks the system to operate software, files, hardware, or commands
- search: needs current or external information
- complex: needs reasoning, protocol knowledge, abstract concepts, or consequential decisions

Never classify URUK, Trinity, Kairos, Coordinate Theory, freedom, entropy,
identity, soul, sovereignty, or system changes as simple.

Output:
{"type": "simple"|"tool"|"search"|"complex", "reason": "short reason", "confidence": 0.0-1.0}
"""


async def classify(
    query: str,
    provider: str = "ollama",
    model: str = "qwen2.5:3b",
    api_base: str = "http://localhost:11434",
    api_key: str = "",
    timeout: float = 2.5,
    temperature: float = 0.0,
    think: bool = False,
    keep_alive: str = "30m",
    context_window: int = 2048,
) -> dict:
    """
    Classify query complexity. Returns dict with keys:
      type: "simple" | "tool" | "search" | "complex"
      reason: str
      confidence: float
      source: "keyword" | "llm" | "fallback"

    Never raises — always returns a valid classification.
    """
    lower = query.lower()

    # ── Fast path 1: Uruk keywords → force complex ────────────────
    if is_protocol_concept_query(query):
        return {
            "type": "complex",
            "reason": "Protocol-level abstract concept detected",
            "confidence": 1.0,
            "source": "keyword",
        }

    if any(kw in lower for kw in _FORCE_COMPLEX):
        return {
            "type": "complex",
            "reason": "Uruk/Trinity keywords detected",
            "confidence": 1.0,
            "source": "keyword",
        }

    if any(kw in lower for kw in _COMPLEX_SIGNALS):
        return {
            "type": "complex",
            "reason": "Reasoning or decision signal detected",
            "confidence": 0.9,
            "source": "keyword",
        }

    # ── Fast path 2: obvious tool request ─────────────────────────
    if any(kw in lower for kw in _TOOL_SIGNALS):
        return {
            "type": "tool",
            "reason": "Tool/automation keywords detected",
            "confidence": 0.9,
            "source": "keyword",
        }

    # ── Fast path 3: obvious search request ───────────────────────
    if any(kw in lower for kw in _SEARCH_SIGNALS):
        return {
            "type": "search",
            "reason": "Search/news keywords detected",
            "confidence": 0.85,
            "source": "keyword",
        }

    # ── Fast path 4: very short simple query ──────────────────────
    if len(query) < 80 and any(kw in lower for kw in _SIMPLE_SIGNALS):
        return {
            "type": "simple",
            "reason": "Short factual query pattern",
            "confidence": 0.8,
            "source": "keyword",
        }

    # ── LLM classification (cheap model, short timeout) ───────────
    try:
        import httpx as _httpx
        from services.inference_governor import execute_model_call

        async def _classify_call():
            if provider == "ollama":
                url = f"{api_base.rstrip('/')}/api/generate"
                body = {
                    "model": model,
                    "prompt": PRE_GATE_SYSTEM + f"\n\n用戶輸入：{query[:300]}",
                    "stream": False,
                    "think": bool(think),
                    "keep_alive": keep_alive,
                    "options": {
                        "temperature": float(temperature),
                        "num_predict": 96,
                        "num_ctx": int(context_window),
                    },
                }
                body["prompt"] = f"{PRE_GATE_SYSTEM}\n\nUSER INPUT:\n{query[:300]}"
                async with _httpx.AsyncClient(timeout=timeout) as client:
                    r = await client.post(url, json=body)
                    r.raise_for_status()
                    return r.json().get("response", "")

            _key = api_key or os.environ.get("OPENAI_API_KEY", "")
            headers = {"Authorization": f"Bearer {_key}", "Content-Type": "application/json"}
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": PRE_GATE_SYSTEM},
                    {"role": "user", "content": query[:300]},
                ],
                "max_tokens": 96,
                "temperature": float(temperature),
            }
            async with _httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(
                    f"{api_base.rstrip('/')}/chat/completions",
                    headers=headers, json=body,
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]

        raw = await execute_model_call(
            _classify_call,
            role="pre_gate",
            provider=provider,
            model=model,
        )

        # Parse JSON from response
        m = re.search(r"\{.*?\}", raw, re.DOTALL)
        if m:
            result = json.loads(m.group(0))
            result["source"] = "llm"
            # Validate type field
            if result.get("type") not in ("simple", "tool", "search", "complex"):
                result["type"] = "complex"
            return result

    except Exception as e:
        pass  # Fallback below

    # ── Fallback: length-based heuristic ──────────────────────────
    n = len(query)
    if n < 60:
        return {"type": "simple", "reason": "Short query fallback", "confidence": 0.5, "source": "fallback"}
    if n > 300:
        return {"type": "complex", "reason": "Long query fallback", "confidence": 0.5, "source": "fallback"}
    return {"type": "complex", "reason": "Default fallback", "confidence": 0.3, "source": "fallback"}
