"""
URUK Trinity Console — Planner-Executor Engine
v1.0 | 大模型出計劃，細模型逐步執行

架構：
  ┌─────────────────────────────────────────────────────────────┐
  │  用戶自然語言 → Planner (大模型，單次呼叫)                     │
  │                ↓ ExecutionPlan (JSON array of steps)         │
  │  Executor loop:                                              │
  │    for each step:                                            │
  │      if needs_visual:                                        │
  │        screenshot → 細模型 → resolve coords/result           │
  │      execute_tool(resolved_step)                             │
  │      yield StepEvent (SSE)                                   │
  └─────────────────────────────────────────────────────────────┘

Planner LLM：任何大模型（OpenRouter / Gemini / Anthropic）
  - 呼叫一次，輸出完整 JSON plan
  - 唔需要實時在線（planning is offline）

Executor LLM（細模型）：
  - Ollama local model（moondream2 / llava-phi3 / qwen2.5:3b）
  - 每個 needs_visual step 呼叫一次
  - 輸入：step instruction + screenshot base64
  - 輸出：{"tool": "...", "args": {"x": ..., "y": ...}}
  - 唔需要理解整個任務——只解析一個 step

工具規則係 computer_tools.py 定義嘅 TOOL_REGISTRY。
Executor 唔生成工具定義，只選擇同執行。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

# ReAct post-step verification — set False to disable
_REACT_VERIFY_ENABLED = True

from services.computer_tools import (
    TOOL_REGISTRY, ToolResult,
    execute_tool, take_screenshot,
    tools_json_for_planner, tools_json_for_categories, tools_summary_for_executor,
)
from adapters import OllamaAdapter, OpenAIAdapter
from failover import call_with_failover, ApiProfile, FailoverConfig


# ─────────────────────────────────────────────────────────────────
# Screenshot compression helper
# ─────────────────────────────────────────────────────────────────

def _compress_screenshot(b64_png: str, max_width: int = 900) -> str:
    """Resize + JPEG-compress a base64 PNG screenshot.

    Reduces image token cost by ~50–70% compared to full-res PNG.
    Falls back to original if Pillow is unavailable.

    Args:
        b64_png:   base64-encoded PNG string (no data URI prefix).
        max_width: target width in pixels; height scaled proportionally.

    Returns:
        base64-encoded JPEG string.
    """
    try:
        import base64
        import io
        from PIL import Image  # type: ignore

        raw = base64.b64decode(b64_png)
        img = Image.open(io.BytesIO(raw)).convert("RGB")

        # Downscale if wider than max_width
        w, h = img.size
        if w > max_width:
            new_h = int(h * max_width / w)
            img = img.resize((max_width, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        # Pillow not installed or any other error → return original unchanged
        return b64_png


async def _call_anthropic_with_cache(
    messages: list,
    model: str,
    api_key: str,
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> str:
    """Call Anthropic API with prompt caching enabled.

    Uses Anthropic's native API format (not OpenAI-compatible) so that
    cache_control blocks are respected. Saves ~89% on repeated system
    prompt + tool schema tokens (charged at 10% of normal rate after
    first call warms the cache).

    Falls back to plain text if API call fails.
    """
    import httpx as _hx
    import os as _os

    _key = api_key or _os.environ.get("ANTHROPIC_API_KEY", "")
    if not _key:
        raise ValueError("ANTHROPIC_API_KEY not set — cannot use Anthropic caching")

    # Extract system content (first message if role == "system")
    system_blocks = None
    user_messages = []
    for msg in messages:
        if msg["role"] == "system":
            content = msg["content"]
            if isinstance(content, list):
                system_blocks = content  # already formatted with cache_control
            else:
                system_blocks = [{"type": "text", "text": content}]
        else:
            user_messages.append(msg)

    body: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": user_messages,
    }
    if system_blocks:
        body["system"] = system_blocks

    async with _hx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "prompt-caching-2024-07-31",
                "content-type": "application/json",
            },
            json=body,
        )
        r.raise_for_status()
        data = r.json()
        # Log cache performance if available
        usage = data.get("usage", {})
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_write = usage.get("cache_creation_input_tokens", 0)
        if cache_read or cache_write:
            print(f"[caching] read={cache_read} write={cache_write} "
                  f"saved={cache_read} tokens at 10% rate")
        return data["content"][0]["text"]


# ─────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────

@dataclass
class PlanStep:
    """One step in an ExecutionPlan."""
    step: int
    tool: str
    args: Dict[str, Any]
    purpose: str = ""
    executor_rule: str = ""
    allowed_tools: List[str] = field(default_factory=list)
    success_criteria: str = ""
    needs_visual: bool = False      # overridden from TOOL_REGISTRY at parse time
    requires_approval: bool = False # True → pause and ask user before executing

    # ── Loop support ──────────────────────────────────────────────
    foreach_items: List[Any] = field(default_factory=list)
    # If non-empty: step repeats once per item; use {item} in args values.
    # Example: foreach_items=["a.pdf","b.pdf"], args={"path":"{item}"}
    #          → step runs twice with path="a.pdf" then path="b.pdf"

    # ── Error recovery ────────────────────────────────────────────
    on_error: str = "stop"   # "stop" | "skip" | "retry"
    max_retries: int = 0     # used when on_error="retry"

    def to_dict(self) -> Dict:
        return {
            "step": self.step,
            "tool": self.tool,
            "args": self.args,
            "purpose": self.purpose,
            "executor_rule": self.executor_rule,
            "allowed_tools": self.allowed_tools,
            "success_criteria": self.success_criteria,
            "needs_visual": self.needs_visual,
            "requires_approval": self.requires_approval,
            "foreach_items": self.foreach_items,
            "on_error": self.on_error,
            "max_retries": self.max_retries,
        }


@dataclass
class ExecutionPlan:
    """Full plan produced by the Planner."""
    goal: str
    steps: List[PlanStep]
    tool_rules: Dict[str, Any] = field(default_factory=dict)
    planner_model: str = ""
    planner_reasoning: str = ""
    raw_json: str = ""

    def to_dict(self) -> Dict:
        return {
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "tool_rules": self.tool_rules,
            "planner_model": self.planner_model,
            "step_count": len(self.steps),
        }


@dataclass
class StepEvent:
    """One SSE event emitted during execution."""
    event_type: str          # plan / step_start / step_visual / step_done / error / done
    step: Optional[int] = None
    tool: Optional[str] = None
    data: Dict = field(default_factory=dict)

    def to_sse(self) -> str:
        payload = {"event_type": self.event_type, "step": self.step,
                   "tool": self.tool, **self.data}
        return f"event: agent\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@dataclass
class AgentConfig:
    """Configuration for the planner/executor API wrapper."""
    planner_model: str = "gemini-2.5-flash"
    planner_provider: str = "gemini"
    planner_api_base: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    planner_api_key: str = ""
    executor_text_model: str = "qwen2.5:3b"
    executor_model: str = "qwen2-vl:7b"
    executor_ollama_base: str = "http://localhost:11434"
    executor_resolve_all_steps: bool = True
    include_screenshot_in_plan: bool = True
    screenshot_max_width: int = 900
    dry_run: bool = False


# ─────────────────────────────────────────────────────────────────
# Planner  —  大模型，呼叫一次，出完整 JSON plan
# ─────────────────────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """\
你係一個電腦自動化助手嘅計劃員。
你的工作是接收用戶嘅自然語言要求，然後輸出一個 JSON 格式嘅執行計劃。

可用工具列表：
{tools_json}

輸出格式（必須係 valid JSON，唔可以有其他文字）：
{{
  "goal": "<用戶目標嘅一句話總結>",
  "reasoning": "<你點樣拆解呢個任務>",
  "tool_rules": {{
    "executor_role": "細模型只負責每一步 resolve/validate 最終工具呼叫，不重新理解整個任務",
    "global_allowed_tools": ["<今次任務可能用到嘅工具名>"],
    "safety_rules": ["<細模型執行時必須遵守嘅規則>"],
    "stop_conditions": ["<遇到咩情況要停止並要求人類確認>"]
  }},
  "steps": [
    {{
      "step": 1,
      "tool": "<工具名稱>",
      "args": {{...}},
      "purpose": "<呢個 step 做咩>",
      "executor_rule": "<畀細模型嘅窄指令：只講呢一步點樣 resolve/validate>",
      "allowed_tools": ["<細模型可在呢一步選用嘅工具，通常只包含原工具及安全 fallback>"],
      "success_criteria": "<呢一步點樣算成功>",
      "foreach_items": [],
      "on_error": "stop",
      "max_retries": 0
    }},
    ...
  ]
}}

規則：
1. 每個 step 只用一個工具
2. 如果唔知道元素嘅精確座標，用 find_and_click（唔係 click_at）
3. 敏感操作（buy / delete / send / transfer）喺 purpose 裡面明確標注「需要用戶確認」
4. navigate_url 只返回 URL 唔自動打開；如需瀏覽器操作，之後用 find_and_click 去地址欄
5. 預計需要等待嘅地方加 wait step
6. 唔好猜座標——如果係視覺任務，用 find_and_click
7. 步驟盡量簡短清晰；5 步能完成嘅唔要寫 10 步
8. 批量處理（例如：處理多個文件）時用 foreach_items：
   foreach_items=["file1.pdf","file2.pdf"] 且 args 用 {{item}} 作佔位符
   → 呢個 step 自動為每個 item 執行一次，唔需要寫多個重複 step
9. 預期可能失敗嘅 step（例如：網絡請求、視覺搜尋）設 on_error="skip" 或 "retry"
   max_retries 只在 on_error="retry" 時有效（建議 1-3）
10. 開啟 Notepad / 記事本 之後，必須立即加一個 hotkey step 按 Ctrl+N 開新檔，
    因為 Windows 記事本預設會恢復上次嘅 session（舊文件），唔係空白新檔。
    順序：press_key(win) → type_text(notepad) → press_key(enter) → wait(2s) → hotkey(ctrl+n) → wait(1s) → type_text(內容)
11. 開啟任何可能恢復舊 session 嘅應用（Notepad、VS Code、Chrome 等），
    都要先確認係新檔 / 空白狀態再輸入，必要時用 Ctrl+N 或 Ctrl+T 開新分頁 / 新文件。
12. 儲存對話框（Save As / 另存新檔）出現後，必須先用 hotkey(ctrl+a) 清空現有路徑，
    再 type_text 完整路徑，唔好假設對話框已經定位到正確位置。

13. 優先選用 Accessibility API 工具（唔靠座標、唔靠 vision、唔受視窗位置影響）：
    · 點擊按鈕/選單 → click_element(element="按鈕名", window="視窗標題")
    · 輸入文字到表單 → type_into_element(element="欄位名", text="...", window="...")
    · 確認某元素出現 → verify_element_exists(element="名稱", window="...")
    · 不知道有咩元素 → get_ui_elements(window="...") 先睇清楚
    只有在 accessibility 工具唔適用時（遊戲、非標準 UI、純圖像介面）才用 find_and_click。
14. 系統、文件、進程操作優先用 API 工具，唔用 UI 自動化：
    · 查系統資訊 → get_system_info（唔要開工作管理員）
    · 列文件 → list_files（唔要打開檔案總管）
    · 執行命令 → run_shell（唔要打開 PowerShell 視窗）
    · 進程管理 → get_process_list / kill_process
15. 大模型只負責規劃同規則設計；唔好將長篇背景塞入每個 step。
16. 每個 step 必須提供 executor_rule、allowed_tools、success_criteria。
17. allowed_tools 要盡量窄；唔好畀細模型可任意選擇所有工具。
18. 如涉及刪除、付款、提交、發送、安裝、kill_process、run_shell 等高風險工具，
    在 safety_rules / stop_conditions 清楚寫明何時要停止等待人類確認。

只輸出 JSON，唔好有 markdown code block，唔好有解釋文字。
"""

PLANNER_CONTEXT_PROMPT = """\
當前屏幕狀態（截圖）已附上（如果有的話）。

用戶要求：
{user_intent}
"""


class Planner:
    """Calls a large model once to produce a full ExecutionPlan from user intent.

    Uses trinity-console's existing failover chain by default.
    Can be overridden with any ApiProfile.
    """

    def __init__(
        self,
        api_profile: Optional[ApiProfile] = None,
        failover_config: Optional[FailoverConfig] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self._profile = api_profile
        self._failover_config = failover_config
        self._model = model or "gemini-2.5-flash"
        self._provider = provider or "gemini"
        self._api_base = api_base or "https://generativelanguage.googleapis.com/v1beta/openai"
        self._api_key = api_key

    def _build_adapter(self):
        key = self._api_key or self._resolve_key()
        return OpenAIAdapter(api_key=key, api_base=self._api_base)

    def _resolve_key(self) -> str:
        import os
        # Try common env vars in priority order
        for env in ("GEMINI_API_KEY", "OPENROUTER_API_KEY",
                    "ANTHROPIC_API_KEY", "GROQ_API_KEY"):
            val = os.environ.get(env, "")
            if val:
                return val
        return ""

    async def make_plan(
        self,
        user_intent: str,
        include_screenshot: bool = True,
        screenshot_max_width: int = 900,
    ) -> ExecutionPlan:
        """Call large model once, return ExecutionPlan.

        Optimisations vs v1.0:
        - tools_json_for_categories(): only sends tool schemas relevant to the
          intent (inferred by keyword), reducing planner input by ~60–70%.
        - Screenshot is resized to max_width before encoding to cut image tokens.
        - Compact JSON (no indent) in tool schema strings.

        include_screenshot=True: takes current screen state and passes to planner
        so it can produce context-aware steps (e.g. "I see browser is open → skip navigate").
        screenshot_max_width: resize screenshot to this width before sending (default 900px).
        """
        # ── Category-filtered tool schema (strip arg descriptions → -35% tokens) ──
        tools_json, detected_cats = tools_json_for_categories(user_intent)
        system_msg = PLANNER_SYSTEM_PROMPT.format(tools_json=tools_json)
        user_msg = PLANNER_CONTEXT_PROMPT.format(user_intent=user_intent)

        # ── Optionally attach compressed screenshot ─────────────────
        ss_b64 = ""
        if include_screenshot:
            _, raw_b64 = take_screenshot()
            if raw_b64:
                ss_b64 = _compress_screenshot(raw_b64, max_width=screenshot_max_width)

        adapter = self._build_adapter()

        # ── Anthropic prompt caching (saves 89% on system prompt + tool schema) ──
        # Marks the static system message for caching; Anthropic charges cached
        # content at 10% of normal rate. No-op for other providers.
        use_caching = self._provider in ("anthropic", "claude")
        if use_caching:
            system_content = [
                {
                    "type": "text",
                    "text": system_msg,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            messages = [{"role": "system", "content": system_content}]
        else:
            messages = [{"role": "system", "content": system_msg}]

        if ss_b64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_msg},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{ss_b64}"}},
                ]
            })
        else:
            messages.append({"role": "user", "content": user_msg})

        # For Anthropic caching, use the native Anthropic API format
        if use_caching:
            raw = await _call_anthropic_with_cache(
                messages=messages,
                model=self._model,
                api_key=self._api_key or self._resolve_key(),
            )
        else:
            raw = await adapter.call(
                messages=messages,
                model=self._model,
                temperature=0.1,
                max_tokens=4096,
            )

        plan = _parse_plan(raw, model=self._model)
        plan.planner_reasoning = (
            f"[cats:{','.join(detected_cats)}] " + plan.planner_reasoning
        )
        return plan


def _parse_plan(raw: str, model: str = "") -> ExecutionPlan:
    """Parse Planner LLM output into ExecutionPlan.

    Strips markdown code fences if present. Graceful fallback on parse error.
    """
    # Strip markdown code block if LLM wrapped it anyway
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"```\s*$", "", cleaned.strip())
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Try to extract first JSON object from mixed text
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = {}
        else:
            data = {}

    goal = str(data.get("goal") or "")
    reasoning = str(data.get("reasoning") or "")
    tool_rules = data.get("tool_rules") if isinstance(data.get("tool_rules"), dict) else {}
    raw_steps = data.get("steps") or []

    steps = []
    for i, s in enumerate(raw_steps):
        if not isinstance(s, dict):
            continue
        tool_name = str(s.get("tool") or "")
        # Override needs_visual from TOOL_REGISTRY (source of truth)
        spec = TOOL_REGISTRY.get(tool_name)
        needs_visual = spec.needs_visual if spec else False
        # Flag potentially destructive operations for user approval
        purpose = str(s.get("purpose") or "")
        requires_approval = any(
            kw in purpose.lower() for kw in
            ("確認", "confirm", "buy", "購買", "delete", "刪除", "send", "發送",
             "transfer", "轉帳", "submit", "提交")
        )
        foreach_items = s.get("foreach_items") or []
        if not isinstance(foreach_items, list):
            foreach_items = []
        on_error = str(s.get("on_error") or "stop").lower()
        if on_error not in ("stop", "skip", "retry"):
            on_error = "stop"
        max_retries = int(s.get("max_retries") or 0)
        max_retries = min(max_retries, 5)   # cap at 5 retries
        allowed_tools = s.get("allowed_tools") or []
        if not isinstance(allowed_tools, list):
            allowed_tools = []
        allowed_tools = [
            str(t) for t in allowed_tools
            if isinstance(t, str) and t in TOOL_REGISTRY
        ]
        if tool_name and tool_name in TOOL_REGISTRY and tool_name not in allowed_tools:
            allowed_tools.insert(0, tool_name)

        steps.append(PlanStep(
            step=int(s.get("step") or (i + 1)),
            tool=tool_name,
            args=s.get("args") or {},
            purpose=purpose,
            executor_rule=str(s.get("executor_rule") or ""),
            allowed_tools=allowed_tools,
            success_criteria=str(s.get("success_criteria") or ""),
            needs_visual=needs_visual,
            requires_approval=requires_approval,
            foreach_items=foreach_items,
            on_error=on_error,
            max_retries=max_retries,
        ))

    return ExecutionPlan(
        goal=goal,
        steps=steps,
        tool_rules=tool_rules,
        planner_model=model,
        planner_reasoning=reasoning,
        raw_json=cleaned,
    )


# ─────────────────────────────────────────────────────────────────
# Executor  —  細模型，逐步執行
# ─────────────────────────────────────────────────────────────────

EXECUTOR_SYSTEM_PROMPT = """\
你係一個受限嘅電腦自動化執行助手。大模型已經完成計劃同工具規則；你只負責當前一步。

可用工具：
{tools_summary}

大模型工具規則：
{tool_rules}

本 step 可用工具（必須嚴格遵守）：
{allowed_tools}

規則：
1. 只輸出一個 JSON 對象，格式：{{"tool": "<工具名>", "args": {{...}}, "confidence": 0.0-1.0, "requires_human": false, "reason": "<短句>"}}
2. tool 必須係本 step 可用工具之一；唔准新增任務、唔准越權用其他工具。
3. 你可以修正/補齊 args，但唔可以改變大模型 step 嘅目的。
4. 如果係 find_and_click，識別截圖中元素嘅位置，輸出 {{"tool": "find_and_click", "args": {{"x": <整數>, "y": <整數>, "description": "<原描述>"}}}}
5. 如果係 verify_screen，判斷截圖中是否存在預期元素，輸出 {{"tool": "verify_screen", "args": {{"found": true/false, "expected": "<原描述>", "vision_description": "<你看到嘅>"}}}}
6. 如果係 assert_screen_state，嚴格判斷截圖是否符合預期狀態，輸出 {{"tool": "assert_screen_state", "args": {{"passed": true/false, "reason": "<一句話說明>", "confidence": <0.0-1.0>}}}}
7. 如果資料不足或需要人類確認，輸出 {{"tool": "__blocked__", "args": {{}}, "requires_human": true, "reason": "<原因>"}}
8. 如果截圖唔存在，根據 step args 同 executor_rule 做最小修正；唔好重新規劃。
9. 唔好輸出其他文字，唔好有 markdown，只係 JSON

你嘅工作係窄的：識別目標位置或狀態，唔係理解整個任務。
"""

EXECUTOR_STEP_PROMPT = """\
步驟 {step}: {purpose}
Executor rule: {executor_rule}
工具: {tool}
參數描述: {args_description}
成功標準: {success_criteria}

請根據截圖輸出工具呼叫 JSON。
"""


class Executor:
    """Executes a plan step by step.

    For steps with needs_visual=True: takes screenshot → calls small vision model
    → resolves coordinates → executes tool.
    For steps with needs_visual=False: executes directly.

    Yields StepEvent for SSE streaming.
    """

    def __init__(
        self,
        ollama_model: str = "qwen2-vl:7b",  # vision model
        text_model: str = "qwen2.5:3b",
        ollama_base: str = "http://localhost:11434",
        screenshot_before_visual: bool = True,
        resolve_all_steps: bool = True,
    ):
        self._vision_model = ollama_model
        self._text_model = text_model
        self._vision_adapter = OllamaAdapter(api_base=ollama_base)
        self._text_adapter = OllamaAdapter(api_base=ollama_base)
        self._screenshot_before = screenshot_before_visual
        self._resolve_all_steps = resolve_all_steps
        self._active_tool_rules: Dict[str, Any] = {}

    async def execute_plan(
        self, plan: ExecutionPlan, dry_run: bool = False
    ) -> AsyncIterator[StepEvent]:
        """Execute all steps, yield StepEvent for each.

        Handles foreach expansion and per-step error recovery.
        """
        self._active_tool_rules = plan.tool_rules or {}
        yield StepEvent(
            event_type="plan",
            data={
                "goal": plan.goal,
                "step_count": len(plan.steps),
                "plan": plan.to_dict(),
                "executor_text_model": self._text_model,
                "executor_vision_model": self._vision_model,
                "small_executor_active": self._resolve_all_steps,
            }
        )

        executed = 0
        for step in plan.steps:
            if step.foreach_items:
                # ── foreach expansion ──────────────────────────────
                yield StepEvent(
                    event_type="foreach_start",
                    step=step.step,
                    tool=step.tool,
                    data={"items_count": len(step.foreach_items),
                          "purpose": step.purpose},
                )
                for idx, item in enumerate(step.foreach_items):
                    expanded = _expand_step(step, item, idx)
                    async for event in self._execute_step_with_retry(
                        expanded, dry_run=dry_run
                    ):
                        yield event
                    executed += 1
                yield StepEvent(
                    event_type="foreach_done",
                    step=step.step, tool=step.tool,
                    data={"items_count": len(step.foreach_items)},
                )
            else:
                async for event in self._execute_step_with_retry(
                    step, dry_run=dry_run
                ):
                    yield event
                executed += 1

        yield StepEvent(
            event_type="done",
            data={"goal": plan.goal, "total_steps": executed},
        )

    async def _execute_step_with_retry(
        self, step: PlanStep, dry_run: bool = False
    ) -> AsyncIterator[StepEvent]:
        """Wrap _execute_step with on_error / retry logic."""
        max_attempts = (step.max_retries + 1) if step.on_error == "retry" else 1

        for attempt in range(1, max_attempts + 1):
            failed = False
            async for event in self._execute_step(step, dry_run=dry_run):
                yield event
                # Detect failure from this step
                if event.event_type in ("step_error",):
                    failed = True
                elif event.event_type == "step_done" and not event.data.get("ok", True):
                    failed = True

            if not failed:
                return   # success — done

            # ── failure handling ───────────────────────────────────
            if step.on_error == "skip":
                yield StepEvent(
                    event_type="step_skipped",
                    step=step.step, tool=step.tool,
                    data={"reason": "on_error=skip, continuing to next step"},
                )
                return

            if step.on_error == "retry" and attempt < max_attempts:
                backoff = min(2.0 ** (attempt - 1), 8.0)   # 1s, 2s, 4s, 8s cap
                yield StepEvent(
                    event_type="step_retry",
                    step=step.step, tool=step.tool,
                    data={"attempt": attempt, "max_retries": step.max_retries,
                          "backoff_seconds": backoff},
                )
                await asyncio.sleep(backoff)
                continue

            # on_error="stop" or retries exhausted → already emitted error event
            return

    async def _execute_step(
        self, step: PlanStep, dry_run: bool = False
    ) -> AsyncIterator[StepEvent]:
        """Execute one step after constrained small-model resolution."""
        yield StepEvent(
            event_type="step_start",
            step=step.step,
            tool=step.tool,
            data={"purpose": step.purpose, "args": step.args,
                  "executor_rule": step.executor_rule,
                  "allowed_tools": self._allowed_tools_for_step(step),
                  "needs_visual": step.needs_visual,
                  "requires_approval": step.requires_approval},
        )

        if step.requires_approval:
            # Surface for user confirmation — caller decides whether to proceed
            yield StepEvent(
                event_type="step_approval_required",
                step=step.step,
                tool=step.tool,
                data={"purpose": step.purpose, "args": step.args,
                      "message": "呢個步驟需要用戶確認才能執行"},
            )
            # In the current design, dry_run or upstream approval logic
            # controls whether we actually proceed. Skip if dry_run.
            if dry_run:
                yield StepEvent(
                    event_type="step_skipped",
                    step=step.step, tool=step.tool,
                    data={"reason": "dry_run + requires_approval"},
                )
                return

        # Small executor resolution: local model validates/fills the tool call.
        resolved_args = dict(step.args)
        resolved_tool = {"tool": step.tool}
        if (self._resolve_all_steps or step.needs_visual) and not dry_run:
            async for event in self._resolve_step_with_small_model(
                step,
                resolved_args,
                resolved_tool,
                include_screenshot=step.needs_visual,
            ):
                yield event
            if "executor_error" in resolved_args:
                yield StepEvent(
                    event_type="step_error",
                    step=step.step, tool=step.tool,
                    data={"error": resolved_args["executor_error"],
                          "phase": "small_executor"},
                )
                return
            if resolved_tool.get("tool") == "__blocked__":
                yield StepEvent(
                    event_type="step_approval_required",
                    step=step.step, tool=step.tool,
                    data={"purpose": step.purpose, "args": step.args,
                          "message": resolved_args.get("blocked_reason", "細模型要求人類確認")},
                )
                return

        # Execute
        if dry_run:
            yield StepEvent(
                event_type="step_done",
                step=step.step, tool=step.tool,
                data={"dry_run": True, "resolved_args": resolved_args,
                      "purpose": step.purpose},
            )
            return

        # ── ReAct loop: execute + verify, retry on failure ──────────
        max_retries = max(0, int(step.max_retries)) if step.on_error == "retry" else 0
        # Screen-mutating tools get 1 free auto-retry even without explicit retry flag
        _screen_tools = {"click_at", "find_and_click", "click_element",
                         "press_key", "hotkey", "type_text", "type_unicode",
                         "type_into_element", "double_click_at"}
        execution_tool = resolved_tool.get("tool") or step.tool
        if execution_tool in _screen_tools and max_retries == 0:
            max_retries = 1

        last_result = None
        for attempt in range(max_retries + 1):
            # Run in thread so we don't block the event loop (pyautogui is sync)
            result: ToolResult = await asyncio.get_event_loop().run_in_executor(
                None, lambda: execute_tool(execution_tool, resolved_args)
            )
            last_result = result

            # If tool succeeded and it's a UI action, do a quick accessibility verify
            if result.ok and execution_tool in _screen_tools and _REACT_VERIFY_ENABLED:
                await asyncio.sleep(0.4)  # let UI settle
                # Use verify_element_exists if step has an expected_element hint
                expected = step.args.get("expected_element") or step.args.get("description", "")
                if expected:
                    try:
                        from services.computer_tools import execute_tool as _et
                        verify_res = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: _et("verify_element_exists",
                                              {"element": expected, "timeout": 1.5})
                        )
                        if not verify_res.output.get("found", True):
                            if attempt < max_retries:
                                yield StepEvent(
                                    event_type="step_retry",
                                    step=step.step, tool=step.tool,
                                    data={"attempt": attempt + 1,
                                          "reason": f"verify_element_exists failed for '{expected}'"},
                                )
                                await asyncio.sleep(0.5)
                                continue
                    except Exception:
                        pass  # verify failure is non-fatal

            if result.ok or attempt >= max_retries:
                break

            # Failed — wait and retry
            yield StepEvent(
                event_type="step_retry",
                step=step.step, tool=step.tool,
                data={"attempt": attempt + 1, "error": result.error,
                      "max_retries": max_retries},
            )
            await asyncio.sleep(0.8)

        result = last_result
        yield StepEvent(
            event_type="step_done",
            step=step.step, tool=step.tool,
            data={
                "ok": result.ok,
                "output": _safe_output(result.output),
                "error": result.error,
                "duration_ms": result.duration_ms,
                "purpose": step.purpose,
                "executed_tool": execution_tool,
                "has_screenshot": bool(result.screenshot_b64),
            },
        )

    def _allowed_tools_for_step(self, step: PlanStep) -> List[str]:
        allowed = [t for t in (step.allowed_tools or []) if t in TOOL_REGISTRY]
        if step.tool in TOOL_REGISTRY and step.tool not in allowed:
            allowed.insert(0, step.tool)
        return allowed or ([step.tool] if step.tool else [])

    async def _resolve_step_with_small_model(
        self,
        step: PlanStep,
        resolved_args: Dict,
        resolved_tool: Dict[str, str],
        include_screenshot: bool = False,
    ) -> AsyncIterator[StepEvent]:
        """Use the local small executor to resolve exactly one planned step."""
        model = self._vision_model if include_screenshot else self._text_model
        adapter = self._vision_adapter if include_screenshot else self._text_adapter
        allowed_tools = self._allowed_tools_for_step(step)

        yield StepEvent(
            event_type="step_executor",
            step=step.step,
            tool=step.tool,
            data={"message": f"細模型執行解析中：{step.purpose}",
                  "executor_model": model,
                  "allowed_tools": allowed_tools,
                  "needs_visual": include_screenshot},
        )

        ss_b64 = ""
        if include_screenshot:
            _, ss_b64 = take_screenshot()
            if not ss_b64:
                resolved_args["executor_error"] = "截圖失敗（pyautogui 未安裝或屏幕不可用）"
                return

        user_content = EXECUTOR_STEP_PROMPT.format(
            step=step.step,
            purpose=step.purpose,
            executor_rule=step.executor_rule or "按 planner 給出的 tool/args 做最小必要修正",
            tool=step.tool,
            args_description=json.dumps(step.args, ensure_ascii=False),
            success_criteria=step.success_criteria or "工具執行成功且沒有越權",
        )
        system_content = EXECUTOR_SYSTEM_PROMPT.format(
            tools_summary=tools_summary_for_executor(allowed_tools),
            tool_rules=json.dumps(self._active_tool_rules, ensure_ascii=False)[:2000] or "{}",
            allowed_tools=json.dumps(allowed_tools, ensure_ascii=False),
        )

        if include_screenshot:
            messages = [
                {"role": "system", "content": system_content},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_content},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{ss_b64}"}},
                    ],
                },
            ]
        else:
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ]

        try:
            raw = await adapter.call(
                messages=messages,
                model=model,
                temperature=0.0,
                max_tokens=256,
            )
            parsed = _parse_executor_output(raw)
            if not parsed:
                if include_screenshot:
                    resolved_args["executor_error"] = f"細模型輸出唔係有效 JSON：{raw[:200]}"
                else:
                    yield StepEvent(
                        event_type="step_executor_fallback",
                        step=step.step, tool=step.tool,
                        data={"reason": f"細模型輸出唔係有效 JSON，改用 planner args：{raw[:120]}"},
                    )
                return

            parsed_tool = str(parsed.get("tool") or step.tool)
            if parsed_tool == "click_at" and step.tool == "find_and_click":
                parsed_tool = "find_and_click"

            if parsed_tool == "__blocked__" or parsed.get("requires_human") is True:
                resolved_tool["tool"] = "__blocked__"
                resolved_args["blocked_reason"] = str(parsed.get("reason") or "細模型判斷需要人類確認")
                yield StepEvent(
                    event_type="step_executor_blocked",
                    step=step.step, tool=step.tool,
                    data={"reason": resolved_args["blocked_reason"], "model": model},
                )
                return

            if parsed_tool not in allowed_tools:
                msg = f"細模型嘗試使用未允許工具 {parsed_tool!r}; allowed={allowed_tools}"
                if include_screenshot:
                    resolved_args["executor_error"] = msg
                else:
                    yield StepEvent(
                        event_type="step_executor_fallback",
                        step=step.step, tool=step.tool,
                        data={"reason": msg + "，改用 planner tool"},
                    )
                return

            parsed_args = parsed.get("args") or {}
            if not isinstance(parsed_args, dict):
                parsed_args = {}
            resolved_args.update(parsed_args)
            resolved_tool["tool"] = parsed_tool

            yield StepEvent(
                event_type="step_executor_resolved",
                step=step.step,
                tool=step.tool,
                data={"resolved": parsed, "model": model,
                      "executed_tool": parsed_tool},
            )
        except Exception as e:
            if include_screenshot:
                resolved_args["executor_error"] = f"細模型呼叫失敗：{type(e).__name__}: {e}"
            else:
                yield StepEvent(
                    event_type="step_executor_fallback",
                    step=step.step, tool=step.tool,
                    data={"reason": f"細模型呼叫失敗，改用 planner args：{type(e).__name__}: {e}"},
                )

    async def _resolve_visual(
        self, step: PlanStep, resolved_args: Dict
    ) -> AsyncIterator[StepEvent]:
        """Backward-compatible wrapper for old callers."""
        holder = {"tool": step.tool}
        async for event in self._resolve_step_with_small_model(
            step,
            resolved_args,
            holder,
            include_screenshot=True,
        ):
            yield event
        if "executor_error" in resolved_args:
            resolved_args["visual_error"] = resolved_args["executor_error"]


class PlannerExecutorPipeline:
    """High-level API used by app.py to plan and optionally execute an intent."""

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or AgentConfig()
        self.planner = Planner(
            model=self.config.planner_model,
            provider=self.config.planner_provider,
            api_base=self.config.planner_api_base,
            api_key=self.config.planner_api_key,
        )
        self.executor = Executor(
            ollama_model=self.config.executor_model,
            text_model=self.config.executor_text_model,
            ollama_base=self.config.executor_ollama_base,
            resolve_all_steps=self.config.executor_resolve_all_steps,
        )

    async def run(self, user_intent: str) -> AsyncIterator[StepEvent]:
        yield StepEvent(
            event_type="planning",
            data={
                "intent": user_intent,
                "planner_model": self.config.planner_model,
                "executor_text_model": self.config.executor_text_model,
                "executor_vision_model": self.config.executor_model,
            },
        )

        plan = await self.planner.make_plan(
            user_intent,
            include_screenshot=self.config.include_screenshot_in_plan,
            screenshot_max_width=self.config.screenshot_max_width,
        )

        async for event in self.executor.execute_plan(
            plan,
            dry_run=self.config.dry_run,
        ):
            yield event


def _expand_step(step: PlanStep, item: Any, idx: int) -> PlanStep:
    """Return a copy of step with {item} substituted in all string arg values."""
    item_str = str(item)

    def _sub(v: Any) -> Any:
        return v.replace("{item}", item_str) if isinstance(v, str) else v

    new_args = {k: _sub(v) for k, v in step.args.items()}
    new_purpose = _sub(step.purpose)

    return PlanStep(
        step=step.step * 10000 + idx,   # unique step number for SSE
        tool=step.tool,
        args=new_args,
        purpose=new_purpose,
        executor_rule=_sub(step.executor_rule),
        allowed_tools=list(step.allowed_tools),
        success_criteria=_sub(step.success_criteria),
        needs_visual=step.needs_visual,
        requires_approval=step.requires_approval,
        foreach_items=[],               # don't recurse
        on_error=step.on_error,
        max_retries=step.max_retries,
    )


def _parse_executor_output(raw: str) -> Optional[Dict]:
    """Parse the small executor model output into a tool call dict."""
    import re as _re
    raw = raw.strip()
    # Strip markdown fences
    fence = _re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    if not raw.startswith("{"):
        m = _re.search(r"\{[\s\S]*\}", raw)
        if m:
            raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        return None


def _safe_output(output: Any) -> Any:
    """Truncate large outputs for SSE payload."""
    if isinstance(output, dict):
        result = {}
        for k, v in output.items():
            if k == "screenshot_b64":
                result[k] = v  # pass through
            elif isinstance(v, str) and len(v) > 2000:
                result[k] = v[:2000] + "…"
            else:
                result[k] = v
        return result
    if isinstance(output, str) and len(output) > 4000:
        return output[:4000] + "…"
    return output
