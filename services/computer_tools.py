"""
URUK Trinity Console — Computer Tools Registry
v1.0 | Planner-Executor 架構嘅工具規則層

設計原則：
  - 工具規則係 DETERMINISTIC（預先寫死，唔係由 LLM 生成）
  - 每個工具有明確嘅 schema：name / description / args_schema / needs_visual
  - needs_visual=True  → Executor 先截圖再呼叫細模型解析 target
  - needs_visual=False → Executor 直接執行，唔需要細模型
  - 執行層用 pyautogui（desktop）或 httpx（web navigation）

TOOL_REGISTRY 係呢個模組唯一嘅 public symbol。
所有 step execution 由 execute_tool() 處理。
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import pathlib
import sys
import tempfile
from datetime import datetime

# ── optional imports ──────────────────────────────────────────────
try:
    import pyautogui
    _PYAUTOGUI_AVAILABLE = True
    pyautogui.PAUSE = 0.3
    pyautogui.FAILSAFE = True
except ImportError:
    _PYAUTOGUI_AVAILABLE = False

try:
    from PIL import Image as _PILImage
    from PIL import ImageGrab as _ImageGrab
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False
    _ImageGrab = None

try:
    from pywinauto import Application as _PWApp  # type: ignore
    _PYWINAUTO_AVAILABLE = True
except Exception:
    _PWApp = None
    _PYWINAUTO_AVAILABLE = False

try:
    import pdfplumber as _pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False

try:
    import docx as _docx_module
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False

try:
    import pyperclip as _pyperclip
    _PYPERCLIP_AVAILABLE = True
except ImportError:
    _PYPERCLIP_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────
# Checkpoint directory — persists agent task state across steps
# ─────────────────────────────────────────────────────────────────
_CHECKPOINT_DIR = pathlib.Path(tempfile.gettempdir()) / "uruk_agent_checkpoints"


# ─────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────

@dataclass
class ArgSpec:
    """Single argument definition for a tool."""
    name: str
    type: str          # "str" | "int" | "float" | "bool"
    required: bool = True
    default: Any = None
    description: str = ""


@dataclass
class ToolSpec:
    """Complete definition of one tool in the registry.

    name           — snake_case identifier (used in plan JSON)
    description    — what this tool does (shown to both Planner LLM and Executor LLM)
    args           — ordered list of ArgSpec
    needs_visual   — True → Executor takes screenshot first and asks small model to
                     interpret target coords before calling execute_tool()
    category       — "mouse" | "keyboard" | "screen" | "nav" | "file" | "wait"
    """
    name: str
    description: str
    args: List[ArgSpec] = field(default_factory=list)
    needs_visual: bool = False
    category: str = "misc"

    def args_schema(self, strip_descriptions: bool = False) -> Dict:
        """Return JSON-schema-style dict for this tool's arguments.

        strip_descriptions=True removes per-arg descriptions from the schema,
        saving ~35% of planner input tokens. Planner can still see arg names
        and types; descriptions are mainly helpful for human readers.
        """
        props = {}
        required = []
        for a in self.args:
            entry: Dict = {"type": a.type}
            if not strip_descriptions:
                entry["description"] = a.description
            if a.default is not None:
                entry["default"] = a.default
            props[a.name] = entry
            if a.required:
                required.append(a.name)
        return {"type": "object", "properties": props, "required": required}

    def to_dict(self, strip_arg_descriptions: bool = False) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "args_schema": self.args_schema(strip_descriptions=strip_arg_descriptions),
            "needs_visual": self.needs_visual,
            "category": self.category,
        }


# ─────────────────────────────────────────────────────────────────
# Tool Registry — DETERMINISTIC RULES
# 只改呢度就可以增加或修改工具，唔需要改其他代碼
# ─────────────────────────────────────────────────────────────────

TOOL_REGISTRY: Dict[str, ToolSpec] = {}

# Custom-tool dispatch table: name → execute(args) callable
# Populated by _load_custom_tools() at module init + on hot-reload.
_CUSTOM_DISPATCH: Dict[str, Any] = {}
# Directory where AI-generated tool modules live
_CUSTOM_TOOLS_DIR = pathlib.Path(__file__).parent / "custom_tools"


def _reg(spec: ToolSpec) -> ToolSpec:
    TOOL_REGISTRY[spec.name] = spec
    return spec


def _load_custom_tools() -> List[str]:
    """Scan services/custom_tools/*.py, import/reload each module, register
    its SPEC into TOOL_REGISTRY and its execute() into _CUSTOM_DISPATCH.
    Returns list of loaded tool names."""
    import importlib
    import importlib.util

    _CUSTOM_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    init = _CUSTOM_TOOLS_DIR / "__init__.py"
    if not init.exists():
        init.write_text("# URUK custom tools package\n", encoding="utf-8")

    loaded: List[str] = []
    for py_file in sorted(_CUSTOM_TOOLS_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        mod_name = f"services.custom_tools.{py_file.stem}"
        try:
            importlib.import_module("services.custom_tools")
            spec_obj = importlib.util.spec_from_file_location(mod_name, py_file)
            if spec_obj is None:
                continue
            if mod_name in sys.modules and "services.custom_tools" in sys.modules:
                mod = importlib.reload(sys.modules[mod_name])
            else:
                mod = importlib.util.module_from_spec(spec_obj)
                sys.modules[mod_name] = mod
                spec_obj.loader.exec_module(mod)
            tool_spec: ToolSpec = getattr(mod, "SPEC", None)
            execute_fn = getattr(mod, "execute", None)
            if tool_spec is None or execute_fn is None:
                continue
            TOOL_REGISTRY[tool_spec.name] = tool_spec
            _CUSTOM_DISPATCH[tool_spec.name] = execute_fn
            loaded.append(tool_spec.name)
        except Exception as _e:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "custom_tools: failed to load %s: %s", py_file.name, _e
            )
    return loaded


# ── Screen ───────────────────────────────────────────────────────

_reg(ToolSpec(
    name="screenshot",
    description="截取當前屏幕快照。返回 base64 圖像。通常係每個 step 開始前自動執行嘅狀態確認。",
    args=[],
    needs_visual=False,
    category="screen",
))

_reg(ToolSpec(
    name="read_screen_text",
    description="返回當前屏幕上可見嘅文字內容（純文字，無圖像）。適合確認頁面內容、讀取結果文字。",
    args=[],
    needs_visual=False,
    category="screen",
))

# ── Mouse ─────────────────────────────────────────────────────────

_reg(ToolSpec(
    name="click_at",
    description="喺屏幕指定座標點擊左鍵。用於已知精確位置嘅點擊。",
    args=[
        ArgSpec("x", "int", True, description="屏幕 x 座標（像素）"),
        ArgSpec("y", "int", True, description="屏幕 y 座標（像素）"),
    ],
    needs_visual=False,
    category="mouse",
))

_reg(ToolSpec(
    name="find_and_click",
    description=(
        "根據視覺描述搵到屏幕上嘅元素然後點擊。"
        "需要細模型先看截圖，返回 x/y 座標，再執行 click_at。"
        "用於唔知具體座標但知道要點擊咩嘅情況（例如：『提交按鈕』、『搜尋框』）。"
    ),
    args=[
        ArgSpec("description", "str", True,
                description="要點擊嘅元素嘅視覺描述（例如：'藍色提交按鈕'、'第一個搜尋結果'）"),
    ],
    needs_visual=True,
    category="mouse",
))

_reg(ToolSpec(
    name="right_click_at",
    description="喺指定座標右鍵點擊。",
    args=[
        ArgSpec("x", "int", True, description="屏幕 x 座標"),
        ArgSpec("y", "int", True, description="屏幕 y 座標"),
    ],
    needs_visual=False,
    category="mouse",
))

_reg(ToolSpec(
    name="double_click_at",
    description="喺指定座標雙擊左鍵。",
    args=[
        ArgSpec("x", "int", True, description="屏幕 x 座標"),
        ArgSpec("y", "int", True, description="屏幕 y 座標"),
    ],
    needs_visual=False,
    category="mouse",
))

_reg(ToolSpec(
    name="scroll",
    description="喺當前滑鼠位置（或指定位置）滾動屏幕。",
    args=[
        ArgSpec("direction", "str", True,
                description="滾動方向：'up' 向上 / 'down' 向下"),
        ArgSpec("amount", "int", False, default=3,
                description="滾動格數（默認 3）"),
        ArgSpec("x", "int", False, default=None, description="滾動位置 x（可選）"),
        ArgSpec("y", "int", False, default=None, description="滾動位置 y（可選）"),
    ],
    needs_visual=False,
    category="mouse",
))

_reg(ToolSpec(
    name="move_mouse",
    description="移動滑鼠到指定座標（唔點擊）。",
    args=[
        ArgSpec("x", "int", True, description="目標 x 座標"),
        ArgSpec("y", "int", True, description="目標 y 座標"),
    ],
    needs_visual=False,
    category="mouse",
))

# ── Keyboard ──────────────────────────────────────────────────────

_reg(ToolSpec(
    name="type_text",
    description="喺當前焦點位置輸入文字。會逐個字符輸入（唔係貼上）。",
    args=[
        ArgSpec("text", "str", True, description="要輸入嘅文字"),
    ],
    needs_visual=False,
    category="keyboard",
))

_reg(ToolSpec(
    name="press_key",
    description=(
        "按下一個或多個按鍵。支援：enter, tab, escape, backspace, delete, "
        "ctrl+c, ctrl+v, ctrl+a, ctrl+z, alt+f4, win, 等。"
    ),
    args=[
        ArgSpec("key", "str", True,
                description="按鍵名稱（例如：'enter'、'ctrl+c'、'tab'）"),
    ],
    needs_visual=False,
    category="keyboard",
))

_reg(ToolSpec(
    name="hotkey",
    description="同時按下多個按鍵（組合鍵）。",
    args=[
        ArgSpec("keys", "str", True,
                description="組合鍵，用逗號分隔（例如：'ctrl,shift,esc'）"),
    ],
    needs_visual=False,
    category="keyboard",
))

# ── Navigation ────────────────────────────────────────────────────

_reg(ToolSpec(
    name="navigate_url",
    description=(
        "通知用戶應該喺瀏覽器打開指定 URL。"
        "注意：因安全限制，呢個工具唔會自動打開瀏覽器——"
        "會返回 URL 讓用戶確認後再執行，或配合 find_and_click 點擊地址欄輸入。"
    ),
    args=[
        ArgSpec("url", "str", True, description="目標 URL（需包含 https://）"),
    ],
    needs_visual=False,
    category="nav",
))

# ── Wait / Control ────────────────────────────────────────────────

_reg(ToolSpec(
    name="wait",
    description="等待指定秒數。用於等待頁面加載或動畫完成。",
    args=[
        ArgSpec("seconds", "float", False, default=1.0,
                description="等待秒數（默認 1.0 秒）"),
    ],
    needs_visual=False,
    category="wait",
))

_reg(ToolSpec(
    name="verify_screen",
    description=(
        "截圖並讓細模型確認屏幕上是否存在某個預期元素或狀態。"
        "返回 {'found': true/false, 'description': ...}。"
        "用於 step 完成後嘅狀態驗證。"
    ),
    args=[
        ArgSpec("expected", "str", True,
                description="預期喺屏幕上看到嘅元素或狀態描述"),
    ],
    needs_visual=True,
    category="screen",
))

# ── File ──────────────────────────────────────────────────────────

_reg(ToolSpec(
    name="read_file",
    description="讀取本地文件內容。",
    args=[
        ArgSpec("path", "str", True, description="文件絕對路徑"),
        ArgSpec("encoding", "str", False, default="utf-8",
                description="文字編碼（默認 utf-8）"),
    ],
    needs_visual=False,
    category="file",
))

_reg(ToolSpec(
    name="write_file",
    description="將文字內容寫入本地文件（覆蓋模式）。",
    args=[
        ArgSpec("path", "str", True, description="文件絕對路徑"),
        ArgSpec("content", "str", True, description="要寫入嘅內容"),
        ArgSpec("encoding", "str", False, default="utf-8",
                description="文字編碼（默認 utf-8）"),
    ],
    needs_visual=False,
    category="file",
))

# ── Document Extraction ───────────────────────────────────────────

_reg(ToolSpec(
    name="extract_document",
    description=(
        "從本地文件提取結構化內容。支援 PDF、DOCX、TXT、CSV、MD 格式。"
        "output_format='json' 返回結構化 dict（含段落、表格）；"
        "'markdown' 返回 Markdown 文字；'text' 返回純文字。"
        "係市場最缺嘅 agent-callable 文件提取工具——唔需要外部 SaaS，本地執行。"
    ),
    args=[
        ArgSpec("path", "str", True, description="文件絕對路徑"),
        ArgSpec("output_format", "str", False, default="text",
                description="輸出格式：'json' / 'markdown' / 'text'（默認 text）"),
        ArgSpec("max_chars", "int", False, default=16000,
                description="最大字符數（默認 16000）"),
    ],
    needs_visual=False,
    category="file",
))

# ── Visual Assertion ──────────────────────────────────────────────

_reg(ToolSpec(
    name="assert_screen_state",
    description=(
        "截圖並讓細模型嚴格驗證屏幕狀態是否符合預期。"
        "返回 {passed: bool, reason: str, confidence: float}。"
        "同 verify_screen 唔同：呢個係 pass/fail 斷言工具，適合 workflow 控制流——"
        "例如確認對話框已關閉、文件已保存、按鈕已變灰才繼續下一步。"
    ),
    args=[
        ArgSpec("expected", "str", True,
                description="預期屏幕狀態嘅精確描述（例如：'保存成功提示已出現' / '進度條顯示100%'）"),
        ArgSpec("strict", "bool", False, default=False,
                description="嚴格模式：True=完全符合才 pass；False=大致符合即 pass"),
    ],
    needs_visual=True,
    category="screen",
))

# ── Task State Persistence ────────────────────────────────────────

_reg(ToolSpec(
    name="save_checkpoint",
    description=(
        "保存當前任務執行狀態（checkpoint）到本地文件。"
        "用於長任務的中間狀態保存，支援意外中斷後繼續執行。"
        "checkpoint 存儲位置：系統 temp 目錄 / uruk_agent_checkpoints。"
    ),
    args=[
        ArgSpec("task_id", "str", True,
                description="任務唯一 ID（例如 'copy_report_2026' / 'daily_sync'）"),
        ArgSpec("step", "int", True,
                description="當前已完成嘅步驟序號（0-based）"),
        ArgSpec("context", "str", False, default="{}",
                description="額外上下文 JSON 字符串（例如已提取嘅數據、中間結果）"),
        ArgSpec("note", "str", False, default="",
                description="可讀備注（例如：'已完成下載，下一步係解析'）"),
    ],
    needs_visual=False,
    category="state",
))

_reg(ToolSpec(
    name="load_checkpoint",
    description=(
        "從本地加載任務 checkpoint。"
        "返回 {found: true, task_id, step, context, note, saved_at} 或 {found: false}。"
    ),
    args=[
        ArgSpec("task_id", "str", True, description="任務唯一 ID"),
    ],
    needs_visual=False,
    category="state",
))

_reg(ToolSpec(
    name="list_checkpoints",
    description="列出所有已保存嘅 checkpoints（task_id / step / note / saved_at）。",
    args=[],
    needs_visual=False,
    category="state",
))

# ── Clipboard ─────────────────────────────────────────────────────

_reg(ToolSpec(
    name="read_clipboard",
    description=(
        "讀取系統剪貼板內容。自動嘗試解析為 JSON 或 CSV；失敗則返回原始文字。"
        "返回 {format: 'json'|'csv'|'text', content: ...}。"
        "用於跨應用數據橋接：從 Excel / 瀏覽器 / 其他 app 讀取用戶已複製嘅數據。"
    ),
    args=[],
    needs_visual=False,
    category="clipboard",
))

_reg(ToolSpec(
    name="write_clipboard",
    description=(
        "將內容寫入系統剪貼板。"
        "用於跨應用數據橋接：把 agent 提取嘅結構化數據貼入 Excel / 文字編輯器 / 表單。"
        "content 可以係文字或 JSON 字符串（自動處理序列化）。"
    ),
    args=[
        ArgSpec("content", "str", True,
                description="要寫入剪貼板嘅內容（文字或 JSON 字符串）"),
    ],
    needs_visual=False,
    category="clipboard",
))


# ─────────────────────────────────────────────────────────────────
# ★ NEW TOOLS (v3) — accessibility-based + robust UI control
# ─────────────────────────────────────────────────────────────────

_reg(ToolSpec(
    name="click_element",
    description=(
        "透過 Windows Accessibility API（pywinauto UIA）按元素名稱點擊，"
        "唔需要座標，唔依賴 vision model，視窗移動都唔影響。"
        "比 find_and_click 更可靠——優先用呢個，只有搵唔到元素先用 find_and_click。"
        "例：click_element(window='記事本', element='儲存(S)')。"
    ),
    args=[
        ArgSpec("element", "str", True,  description="元素嘅 accessible name（部分匹配）"),
        ArgSpec("window",  "str", False, description="視窗標題（部分匹配，省略=當前前景視窗）"),
        ArgSpec("control_type", "str", False, description="控件類型過濾：Button/Edit/MenuItem 等"),
        ArgSpec("double",  "bool", False, description="雙擊（默認 False）"),
    ],
    needs_visual=False,
    category="mouse",
))

_reg(ToolSpec(
    name="get_ui_elements",
    description=(
        "列出指定視窗內所有可互動嘅 UI 元素（按鈕、輸入欄、選單等）。"
        "用於 debug：睇清楚視窗裡有咩元素可以點擊，再決定用咩 element 參數。"
    ),
    args=[
        ArgSpec("window",       "str",  False, description="視窗標題（省略=當前前景視窗）"),
        ArgSpec("control_type", "str",  False, description="過濾控件類型（省略=全部）"),
        ArgSpec("max_items",    "int",  False, description="最多返回元素數（默認 50）"),
    ],
    needs_visual=False,
    category="state",
))

_reg(ToolSpec(
    name="type_into_element",
    description=(
        "用 Accessibility API 搵到指定輸入欄，清空後輸入文字。"
        "比 click_at + type_text 更可靠——唔需要知道座標，支援任何 Unicode 文字。"
        "適合：另存新檔對話框、搜索欄、表單欄位。"
    ),
    args=[
        ArgSpec("element", "str", True,  description="輸入欄嘅 accessible name（部分匹配）"),
        ArgSpec("text",    "str", True,  description="要輸入嘅文字（支援 Unicode / 中文）"),
        ArgSpec("window",  "str", False, description="視窗標題（省略=當前前景視窗）"),
        ArgSpec("clear",   "bool", False, description="輸入前先清空（默認 True）"),
    ],
    needs_visual=False,
    category="keyboard",
))

_reg(ToolSpec(
    name="verify_element_exists",
    description=(
        "確認指定視窗內某個 UI 元素係咪存在。"
        "用於 ReAct 驗證步驟：執行操作後確認預期嘅元素出現咗（例如另存對話框、確認按鈕）。"
        "返回 found: true/false + 元素詳情。"
    ),
    args=[
        ArgSpec("element", "str", True,  description="元素嘅 accessible name（部分匹配）"),
        ArgSpec("window",  "str", False, description="視窗標題（省略=任何視窗）"),
        ArgSpec("timeout", "float", False, description="等待元素出現嘅秒數（默認 2.0）"),
    ],
    needs_visual=False,
    category="state",
))

# ─────────────────────────────────────────────────────────────────
# ★ NEW TOOLS (v2) — shell / window / system / drag / unicode
# ─────────────────────────────────────────────────────────────────

_reg(ToolSpec(
    name="run_shell",
    description=(
        "執行 PowerShell 或 cmd 命令並返回輸出（stdout + stderr）。"
        "用於：列出文件、查系統資訊、執行腳本、讀取 process 列表、git 操作等。"
        "輸出上限 8000 字元。Windows 上預設用 PowerShell，shell='cmd' 改用 cmd。"
    ),
    args=[
        ArgSpec("command", "str", True,  description="要執行嘅命令"),
        ArgSpec("shell",   "str", False, description="'powershell'（默認）或 'cmd'"),
        ArgSpec("timeout", "int", False, description="逾時秒數（默認 30）"),
        ArgSpec("cwd",     "str", False, description="工作目錄（默認當前目錄）"),
    ],
    needs_visual=False,
    category="misc",
))

_reg(ToolSpec(
    name="list_files",
    description=(
        "列出指定目錄下嘅文件同子目錄，返回名稱、大小、修改時間。"
        "支援 glob pattern（如 *.py），可遞歸搜索。"
    ),
    args=[
        ArgSpec("path",      "str",  True,  description="目標目錄路徑"),
        ArgSpec("pattern",   "str",  False, description="glob 過濾（如 *.txt，默認 *）"),
        ArgSpec("recursive", "bool", False, description="是否遞歸子目錄（默認 False）"),
        ArgSpec("max_items", "int",  False, description="最多返回條目數（默認 100）"),
    ],
    needs_visual=False,
    category="file",
))

_reg(ToolSpec(
    name="open_app",
    description=(
        "透過程式名稱或完整路徑開啟一個應用程式。"
        "比 Win+搜索 更可靠——直接呼叫 os.startfile / subprocess。"
        "例：open_app('notepad')、open_app('calc')、open_app('C:\\\\path\\\\to\\\\app.exe')。"
    ),
    args=[
        ArgSpec("app",  "str", True,  description="應用程式名稱或完整路徑"),
        ArgSpec("args", "str", False, description="命令行參數（可選）"),
    ],
    needs_visual=False,
    category="nav",
))

_reg(ToolSpec(
    name="get_window_list",
    description=(
        "列出所有當前開啟嘅視窗標題同句柄（handle）。"
        "用於確認某個 app 係咪已開啟、搵到正確視窗再 focus_window。"
    ),
    args=[],
    needs_visual=False,
    category="state",
))

_reg(ToolSpec(
    name="focus_window",
    description=(
        "將指定標題嘅視窗帶到前景（foreground）並給予焦點。"
        "title 係部分匹配（case-insensitive），搵到第一個符合嘅視窗。"
        "用於：切換到 Notepad、Chrome、Excel 等已開啟嘅視窗。"
    ),
    args=[
        ArgSpec("title", "str", True, description="視窗標題（部分匹配即可）"),
    ],
    needs_visual=False,
    category="nav",
))

_reg(ToolSpec(
    name="close_window",
    description=(
        "關閉指定標題嘅視窗（傳送 WM_CLOSE）或關閉當前前景視窗（title 留空）。"
        "比 Alt+F4 更精準——可以針對特定 app 而唔影響其他視窗。"
    ),
    args=[
        ArgSpec("title", "str", False, description="視窗標題（部分匹配，留空=當前前景視窗）"),
    ],
    needs_visual=False,
    category="nav",
))

_reg(ToolSpec(
    name="drag_and_drop",
    description=(
        "從 (start_x, start_y) 拖拽到 (end_x, end_y)，可選持續時間。"
        "用於：拖動文件、調整視窗大小、slider 操作、拖放 UI 元素。"
    ),
    args=[
        ArgSpec("start_x",  "int",   True,  description="起點 X 座標"),
        ArgSpec("start_y",  "int",   True,  description="起點 Y 座標"),
        ArgSpec("end_x",    "int",   True,  description="終點 X 座標"),
        ArgSpec("end_y",    "int",   True,  description="終點 Y 座標"),
        ArgSpec("duration", "float", False, description="拖動時間秒數（默認 0.5）"),
    ],
    needs_visual=False,
    category="mouse",
))

_reg(ToolSpec(
    name="type_unicode",
    description=(
        "輸入包含中文、日文、emoji 等非 ASCII 字元嘅文字。"
        "pyautogui.typewrite 唔支援 Unicode，呢個工具用剪貼板橋接方式輸入任何文字。"
        "流程：寫入剪貼板 → Ctrl+V 貼上。適合輸入廣東話、中文、特殊符號。"
    ),
    args=[
        ArgSpec("text", "str", True, description="要輸入嘅 Unicode 文字"),
    ],
    needs_visual=False,
    category="keyboard",
))

_reg(ToolSpec(
    name="get_system_info",
    description=(
        "返回系統資源使用情況：CPU 使用率、記憶體（總量/可用/使用率）、"
        "磁碟使用率、運行時間、top 5 CPU 進程。唔需要開任何 app。"
    ),
    args=[],
    needs_visual=False,
    category="misc",
))

_reg(ToolSpec(
    name="screenshot_region",
    description=(
        "截取屏幕特定區域嘅截圖（比全屏截圖更精準）。"
        "用於：只睇某個視窗、某個對話框、某個按鈕附近嘅狀態。"
    ),
    args=[
        ArgSpec("x",      "int", True, description="左上角 X 座標"),
        ArgSpec("y",      "int", True, description="左上角 Y 座標"),
        ArgSpec("width",  "int", True, description="寬度（像素）"),
        ArgSpec("height", "int", True, description="高度（像素）"),
    ],
    needs_visual=False,
    category="screen",
))

_reg(ToolSpec(
    name="set_window_position",
    description=(
        "移動並調整指定視窗嘅位置同大小。"
        "用於：整理桌面佈局、將視窗移到特定位置再截圖。"
    ),
    args=[
        ArgSpec("title",  "str", True,  description="視窗標題（部分匹配）"),
        ArgSpec("x",      "int", False, description="左上角 X（省略=不移動）"),
        ArgSpec("y",      "int", False, description="左上角 Y（省略=不移動）"),
        ArgSpec("width",  "int", False, description="寬度（省略=不調整）"),
        ArgSpec("height", "int", False, description="高度（省略=不調整）"),
    ],
    needs_visual=False,
    category="nav",
))

_reg(ToolSpec(
    name="get_process_list",
    description=(
        "返回當前運行嘅進程列表，包括 PID、名稱、CPU%、記憶體（MB）。"
        "可按 cpu 或 memory 排序，返回 top N 條。"
    ),
    args=[
        ArgSpec("sort_by", "str", False, description="排序欄位：'cpu'（默認）或 'memory'"),
        ArgSpec("top_n",   "int", False, description="返回條數（默認 10）"),
    ],
    needs_visual=False,
    category="misc",
))

_reg(ToolSpec(
    name="kill_process",
    description=(
        "終止指定名稱或 PID 嘅進程。"
        "用於：關閉卡死嘅程式、清理測試時開嘅臨時進程。"
        "⚠ 敏感操作，purpose 必須標注原因。"
    ),
    args=[
        ArgSpec("name", "str", False, description="進程名稱（如 notepad.exe）"),
        ArgSpec("pid",  "int", False, description="進程 PID（name 同 pid 至少提供一個）"),
    ],
    needs_visual=False,
    category="misc",
))

_reg(ToolSpec(
    name="download_file",
    description=(
        "從 URL 下載文件並儲存到本地路徑。"
        "支援 HTTP/HTTPS，自動顯示下載進度（bytes）。"
    ),
    args=[
        ArgSpec("url",      "str", True,  description="下載 URL"),
        ArgSpec("save_path","str", True,  description="本地儲存路徑（含文件名）"),
        ArgSpec("timeout",  "int", False, description="逾時秒數（默認 60）"),
    ],
    needs_visual=False,
    category="file",
))

_reg(ToolSpec(
    name="zip_files",
    description=(
        "將一個或多個文件/目錄壓縮成 ZIP 檔案。"
        "paths 係要壓縮嘅文件清單，output 係輸出 ZIP 路徑。"
    ),
    args=[
        ArgSpec("paths",  "list", True,  description="要壓縮嘅文件/目錄路徑列表"),
        ArgSpec("output", "str",  True,  description="輸出 ZIP 文件路徑"),
    ],
    needs_visual=False,
    category="file",
))

_reg(ToolSpec(
    name="get_active_window_title",
    description=(
        "返回當前前景視窗嘅標題。"
        "用於確認某個操作（如 Win+搜索+Enter）之後正確嘅 app 係唔係已經打開。"
    ),
    args=[],
    needs_visual=False,
    category="state",
))


# ─────────────────────────────────────────────────────────────────
# Screenshot helper
# ─────────────────────────────────────────────────────────────────

def tools_json_for_planner(strip_arg_descriptions: bool = True) -> str:
    """Return the complete tool schema JSON for planner prompts."""
    tools = [
        spec.to_dict(strip_arg_descriptions=strip_arg_descriptions)
        for spec in TOOL_REGISTRY.values()
    ]
    return json.dumps(tools, ensure_ascii=False, separators=(",", ":"))


_CATEGORY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "mouse": (
        "click", "double click", "right click", "drag", "drop", "mouse",
        "button", "select", "press on",
    ),
    "keyboard": (
        "type", "write", "paste", "keyboard", "hotkey", "shortcut", "key",
        "ctrl", "enter", "tab", "escape",
    ),
    "screen": (
        "screen", "screenshot", "look", "see", "visible", "verify", "check",
        "read screen", "ocr",
    ),
    "nav": (
        "url", "website", "browser", "navigate", "open page", "go to",
        "back", "forward", "refresh",
    ),
    "file": (
        "file", "folder", "directory", "path", "read", "save", "write",
        "download", "zip", "pdf", "docx", "csv", "json",
    ),
    "clipboard": ("clipboard", "copy", "paste"),
    "state": (
        "window", "process", "system", "active", "focus", "list windows",
        "running",
    ),
    "wait": ("wait", "pause", "sleep", "delay"),
    "misc": ("shell", "command", "powershell", "terminal", "run"),
}


def _detect_tool_categories(user_intent: str) -> List[str]:
    """Infer a compact but safe set of tool categories for a user request."""
    text = (user_intent or "").lower()
    detected = {
        category
        for category, keywords in _CATEGORY_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    }

    # Most desktop plans need observation and short waits even when not explicit.
    detected.update({"screen", "wait", "state"})

    # Keep basic input tools available for UI tasks.
    if detected.intersection({"screen", "nav", "state", "mouse", "keyboard"}):
        detected.update({"mouse", "keyboard"})

    # Shell and filesystem tools are often paired.
    if detected.intersection({"file", "misc"}):
        detected.update({"file", "misc"})

    return sorted(detected)


def tools_json_for_categories(user_intent: str) -> Tuple[str, List[str]]:
    """Return planner tool schema JSON filtered to likely relevant categories."""
    categories = _detect_tool_categories(user_intent)
    selected = [
        spec.to_dict(strip_arg_descriptions=True)
        for spec in TOOL_REGISTRY.values()
        if spec.category in categories
    ]

    if not selected:
        selected = [
            spec.to_dict(strip_arg_descriptions=True)
            for spec in TOOL_REGISTRY.values()
        ]
        categories = sorted({spec.category for spec in TOOL_REGISTRY.values()})

    return (
        json.dumps(selected, ensure_ascii=False, separators=(",", ":")),
        categories,
    )


def tools_summary_for_executor(tool_names: Optional[List[str]] = None) -> str:
    """Return a concise text summary of tools available to the small executor."""
    allowed = set(tool_names or [])
    lines = []
    for spec in TOOL_REGISTRY.values():
        if allowed and spec.name not in allowed:
            continue
        arg_names = ", ".join(arg.name for arg in spec.args) or "none"
        lines.append(
            f"- {spec.name}({arg_names}) [{spec.category}] "
            f"needs_visual={spec.needs_visual}: {spec.description}"
        )
    return "\n".join(lines)


def take_screenshot(max_width: int = 1280) -> Tuple[bytes, str]:
    """Take a screenshot and return (raw_bytes, base64_str).

    Priority:
      1. PIL.ImageGrab (Windows built-in, no extra deps)
      2. pyautogui.screenshot (cross-platform fallback)
    Resizes to max_width. Returns (b"", "") on failure.
    """
    img = None

    # ── Priority 1: PIL.ImageGrab (works on Windows w/ Pillow) ────
    if _PIL_AVAILABLE and _ImageGrab is not None:
        try:
            img = _ImageGrab.grab()
        except Exception:
            img = None

    # ── Priority 2: pyautogui ─────────────────────────────────────
    if img is None and _PYAUTOGUI_AVAILABLE:
        try:
            img = pyautogui.screenshot()
        except Exception:
            img = None

    if img is None:
        return b"", ""

    try:
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, int(img.height * ratio)))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=80, optimize=True)
        raw = buf.getvalue()
        return raw, base64.b64encode(raw).decode("utf-8")
    except Exception:
        return b"", ""


# ─────────────────────────────────────────────────────────────────
# Tool execution engine
# ─────────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """Standardised result from one tool execution."""
    tool: str
    args: Dict
    ok: bool
    output: Any = None          # return value (text / dict / None)
    screenshot_b64: str = ""    # post-execution screenshot (if captured)
    error: str = ""
    duration_ms: float = 0.0


def execute_tool(tool_name: str, args: Dict) -> ToolResult:
    """Execute a tool synchronously. Returns ToolResult.

    All pyautogui calls are wrapped so they never raise — errors surface
    in ToolResult.ok=False + ToolResult.error.
    """
    spec = TOOL_REGISTRY.get(tool_name)
    if spec is None:
        return ToolResult(tool=tool_name, args=args, ok=False,
                          error=f"unknown tool: {tool_name!r}")
    t0 = time.time()

    try:
        output = _dispatch(tool_name, args)
        # Capture post-execution screenshot for screen/mouse/keyboard tools
        post_ss = ""
        if spec.category in ("mouse", "keyboard", "nav") and _PYAUTOGUI_AVAILABLE:
            time.sleep(0.3)   # brief settle before capture
            _, post_ss = take_screenshot()
        return ToolResult(
            tool=tool_name, args=args, ok=True,
            output=output, screenshot_b64=post_ss,
            duration_ms=round((time.time() - t0) * 1000, 1),
        )
    except Exception as e:
        return ToolResult(
            tool=tool_name, args=args, ok=False,
            error=f"{type(e).__name__}: {e}",
            duration_ms=round((time.time() - t0) * 1000, 1),
        )


def _dispatch(name: str, args: Dict) -> Any:
    """Inner dispatch — raises on error (caller wraps in try/except)."""

    if name == "screenshot":
        _, b64 = take_screenshot()
        return {"screenshot_b64": b64}

    if name == "read_screen_text":
        # Use pywinauto UIA accessibility tree to collect visible text
        # (no OCR needed — reads accessibility names from foreground window)
        text_parts = []
        if _PYWINAUTO_AVAILABLE and sys.platform == "win32":
            try:
                import ctypes as _ct
                _user32 = _ct.windll.user32
                hwnd = _user32.GetForegroundWindow()
                if hwnd:
                    pw_app = _PWApp(backend="uia").connect(handle=hwnd, timeout=3)
                    win = pw_app.window(handle=hwnd)
                    seen: set = set()
                    def _walk(el, depth=0):
                        if depth > 8:
                            return
                        try:
                            t = (el.window_text() or "").strip()
                            if t and t not in seen and len(t) > 1:
                                seen.add(t)
                                text_parts.append(t)
                        except Exception:
                            pass
                        try:
                            for child in el.children():
                                _walk(child, depth + 1)
                        except Exception:
                            pass
                    _walk(win.wrapper_object())
            except Exception as _e:
                text_parts.append(f"[UIA read error: {_e}]")
        if not text_parts:
            text_parts.append("[read_screen_text: no foreground window text found]")
        return {"text": "\n".join(text_parts)}

    if name == "click_at":
        _require_pyautogui()
        pyautogui.click(int(args["x"]), int(args["y"]))
        return {"clicked": (args["x"], args["y"])}

    if name == "find_and_click":
        # This tool's actual coords are resolved by the Executor (small model)
        # BEFORE calling execute_tool. When execute_tool is called with
        # find_and_click, args should already contain {"x": ..., "y": ...}
        # resolved by the vision step. Fall back to click_at.
        _require_pyautogui()
        x = args.get("x") or args.get("resolved_x")
        y = args.get("y") or args.get("resolved_y")
        if x is None or y is None:
            raise ValueError(
                "find_and_click: 'x' and 'y' must be resolved by Executor vision step "
                "before calling execute_tool. Got args: " + json.dumps(args)
            )
        pyautogui.click(int(x), int(y))
        return {"clicked": (x, y), "description": args.get("description", "")}

    if name == "right_click_at":
        _require_pyautogui()
        pyautogui.rightClick(int(args["x"]), int(args["y"]))
        return {"right_clicked": (args["x"], args["y"])}

    if name == "double_click_at":
        _require_pyautogui()
        pyautogui.doubleClick(int(args["x"]), int(args["y"]))
        return {"double_clicked": (args["x"], args["y"])}

    if name == "scroll":
        _require_pyautogui()
        direction = args.get("direction", "down")
        amount = int(args.get("amount", 3))
        clicks = amount if direction == "up" else -amount
        x = args.get("x")
        y = args.get("y")
        if x is not None and y is not None:
            pyautogui.scroll(clicks, x=int(x), y=int(y))
        else:
            pyautogui.scroll(clicks)
        return {"scrolled": direction, "amount": amount}

    if name == "move_mouse":
        _require_pyautogui()
        pyautogui.moveTo(int(args["x"]), int(args["y"]), duration=0.3)
        return {"moved_to": (args["x"], args["y"])}

    if name == "type_text":
        _require_pyautogui()
        text = str(args.get("text", ""))
        pyautogui.typewrite(text, interval=0.03)
        return {"typed": text[:80] + "..." if len(text) > 80 else text}

    if name == "press_key":
        _require_pyautogui()
        key = str(args.get("key", ""))
        # Handle combo keys like ctrl+c
        if "+" in key:
            parts = [k.strip() for k in key.split("+")]
            pyautogui.hotkey(*parts)
        else:
            pyautogui.press(key)
        return {"pressed": key}

    if name == "hotkey":
        _require_pyautogui()
        keys_str = str(args.get("keys", ""))
        keys = [k.strip() for k in keys_str.split(",")]
        pyautogui.hotkey(*keys)
        return {"hotkey": keys}

    if name == "navigate_url":
        url = str(args.get("url", ""))
        # Return the URL for the caller to handle — security boundary:
        # we don't auto-open URLs; the Executor surfaces this for user review
        return {"url": url, "action": "navigate_pending_user_approval"}

    if name == "wait":
        seconds = float(args.get("seconds", 1.0))
        seconds = min(seconds, 30.0)   # cap at 30s
        time.sleep(seconds)
        return {"waited_seconds": seconds}

    if name == "verify_screen":
        # Coords resolved by vision step (Executor), result injected into args
        found = args.get("found", None)
        if found is None:
            raise ValueError(
                "verify_screen: 'found' must be resolved by Executor vision step."
            )
        return {
            "found": bool(found),
            "expected": args.get("expected", ""),
            "description": args.get("vision_description", ""),
        }

    if name == "read_file":
        path = str(args["path"])
        enc = str(args.get("encoding", "utf-8"))
        content = open(path, encoding=enc).read()
        return {"path": path, "content": content[:8000]}  # cap at 8K chars

    if name == "write_file":
        path = str(args["path"])
        content = str(args["content"])
        enc = str(args.get("encoding", "utf-8"))
        with open(path, "w", encoding=enc) as f:
            f.write(content)
        return {"path": path, "bytes_written": len(content.encode(enc))}

    if name == "extract_document":
        return _extract_document(args)

    if name == "assert_screen_state":
        # Visual resolution done by Executor before calling this tool.
        # Executor asks Ollama: "Does the screen match: <expected>? Answer JSON:
        # {passed: bool, reason: str, confidence: 0.0-1.0}"
        passed = args.get("passed")
        if passed is None:
            raise ValueError(
                "assert_screen_state: 'passed' must be resolved by Executor "
                "vision step before calling execute_tool."
            )
        return {
            "passed": bool(passed),
            "expected": args.get("expected", ""),
            "reason": args.get("reason", ""),
            "confidence": float(args.get("confidence", 0.0)),
        }

    if name == "save_checkpoint":
        return _save_checkpoint(args)

    if name == "load_checkpoint":
        return _load_checkpoint(args)

    if name == "list_checkpoints":
        return _list_checkpoints()

    if name == "read_clipboard":
        return _read_clipboard()

    if name == "write_clipboard":
        return _write_clipboard(args)

    # ── ★ NEW TOOLS (v3) — accessibility-based ───────────────────

    if name == "click_element":
        element_name = str(args.get("element", ""))
        win_title    = str(args.get("window", "")).lower()
        ctrl_type    = args.get("control_type", None)
        double       = bool(args.get("double", False))
        if not _PYWINAUTO_AVAILABLE:
            return {"error": "pywinauto not installed. Run: pip install pywinauto"}
        try:
            import ctypes
            if win_title:
                # find window by title
                found_hwnd = [None]
                def _cb(hwnd, _):
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
                    if win_title in buf.value.lower() and found_hwnd[0] is None:
                        found_hwnd[0] = hwnd
                    return True
                CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                ctypes.windll.user32.EnumWindows(CB(_cb), 0)
                if not found_hwnd[0]:
                    return {"clicked": False, "error": f"Window '{win_title}' not found"}
                app = _PWApp(backend="uia").connect(handle=found_hwnd[0])
                win = app.window(handle=found_hwnd[0])
            else:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                app = _PWApp(backend="uia").connect(handle=hwnd)
                win = app.window(handle=hwnd)

            # Find element
            kwargs = {"best_match": element_name}
            if ctrl_type:
                kwargs["control_type"] = ctrl_type
            el = win.child_window(**kwargs)
            el.wait("visible", timeout=3)
            if double:
                el.double_click_input()
            else:
                el.click_input()
            return {"clicked": True, "element": element_name, "method": "accessibility"}
        except Exception as e:
            # Fallback: try pyautogui locateOnScreen for text matching
            return {"clicked": False, "error": str(e), "hint": "Try get_ui_elements to see available element names"}

    if name == "get_ui_elements":
        win_title  = str(args.get("window", "")).lower()
        ctrl_filter = args.get("control_type", None)
        max_items  = int(args.get("max_items", 50))
        if not _PYWINAUTO_AVAILABLE:
            return {"error": "pywinauto not installed"}
        try:
            import ctypes
            if win_title:
                found_hwnd = [None]
                def _cb2(hwnd, _):
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
                    if win_title in buf.value.lower() and found_hwnd[0] is None:
                        found_hwnd[0] = hwnd
                    return True
                CB2 = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                ctypes.windll.user32.EnumWindows(CB2(_cb2), 0)
                hwnd = found_hwnd[0] or ctypes.windll.user32.GetForegroundWindow()
            else:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
            app = _PWApp(backend="uia").connect(handle=hwnd)
            win = app.window(handle=hwnd)
            elements = []
            def _walk_ui(el, depth=0):
                if len(elements) >= max_items or depth > 6:
                    return
                try:
                    ct  = el.element_info.control_type
                    nm  = el.element_info.name or ""
                    if nm and (not ctrl_filter or ctrl_filter.lower() in ct.lower()):
                        elements.append({"name": nm, "control_type": ct, "depth": depth})
                except Exception:
                    pass
                try:
                    for ch in el.children():
                        _walk_ui(ch, depth+1)
                except Exception:
                    pass
            _walk_ui(win.wrapper_object())
            return {"window": win_title or "foreground", "count": len(elements), "elements": elements}
        except Exception as e:
            return {"error": str(e), "elements": []}

    if name == "type_into_element":
        element_name = str(args.get("element", ""))
        text         = str(args.get("text", ""))
        win_title    = str(args.get("window", "")).lower()
        do_clear     = bool(args.get("clear", True))
        if not _PYWINAUTO_AVAILABLE:
            return {"error": "pywinauto not installed"}
        try:
            import ctypes
            if win_title:
                found_hwnd = [None]
                def _cb3(hwnd, _):
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
                    if win_title in buf.value.lower() and found_hwnd[0] is None:
                        found_hwnd[0] = hwnd
                    return True
                CB3 = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                ctypes.windll.user32.EnumWindows(CB3(_cb3), 0)
                hwnd = found_hwnd[0] or ctypes.windll.user32.GetForegroundWindow()
            else:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
            app = _PWApp(backend="uia").connect(handle=hwnd)
            win = app.window(handle=hwnd)
            el  = win.child_window(best_match=element_name, control_type="Edit")
            el.wait("visible", timeout=3)
            el.click_input()
            if do_clear:
                import pyautogui as _pag
                _pag.hotkey("ctrl", "a")
                time.sleep(0.05)
            # Use clipboard for Unicode support
            _set_clipboard_text(text)
            time.sleep(0.1)
            import pyautogui as _pag2
            _pag2.hotkey("ctrl", "v")
            time.sleep(0.1)
            return {"typed": True, "element": element_name, "text": text, "method": "accessibility+clipboard"}
        except Exception as e:
            return {"typed": False, "error": str(e)}

    if name == "verify_element_exists":
        element_name = str(args.get("element", ""))
        win_title    = str(args.get("window", "")).lower()
        timeout      = float(args.get("timeout", 2.0))
        if not _PYWINAUTO_AVAILABLE:
            # Fallback: just check window title list
            if win_title:
                wl = _dispatch("get_window_list", {})
                found = any(win_title in w.get("title","").lower() for w in wl.get("windows",[]))
                return {"found": found, "method": "window_title_fallback"}
            return {"found": False, "error": "pywinauto not installed"}
        try:
            import ctypes
            if win_title:
                found_hwnd = [None]
                def _cb4(hwnd, _):
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
                    if win_title in buf.value.lower() and found_hwnd[0] is None:
                        found_hwnd[0] = hwnd
                    return True
                CB4 = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                ctypes.windll.user32.EnumWindows(CB4(_cb4), 0)
                hwnd = found_hwnd[0]
                if not hwnd:
                    return {"found": False, "error": f"Window '{win_title}' not found"}
            else:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
            app = _PWApp(backend="uia").connect(handle=hwnd)
            win = app.window(handle=hwnd)
            el = win.child_window(best_match=element_name)
            el.wait("visible", timeout=timeout)
            info = el.element_info
            return {"found": True, "element": element_name,
                    "control_type": info.control_type, "name": info.name}
        except Exception as e:
            return {"found": False, "element": element_name, "error": str(e)}

    # ── ★ NEW TOOLS (v2) ─────────────────────────────────────────

    if name == "run_shell":
        import subprocess, shlex
        command  = str(args.get("command", ""))
        shell_t  = str(args.get("shell", "powershell")).lower()
        timeout  = int(args.get("timeout", 30))
        cwd      = args.get("cwd") or None
        if shell_t == "cmd":
            cmd = ["cmd", "/c", command]
        else:
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                cwd=cwd, encoding="utf-8", errors="replace"
            )
            out = (result.stdout or "") + (result.stderr or "")
            return {
                "stdout": result.stdout[:4000],
                "stderr": result.stderr[:2000],
                "returncode": result.returncode,
                "output": out[:8000],
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out after {timeout}s", "output": ""}
        except Exception as e:
            return {"error": str(e), "output": ""}

    if name == "list_files":
        import glob as _glob
        dir_path  = str(args.get("path", "."))
        pattern   = str(args.get("pattern", "*"))
        recursive = bool(args.get("recursive", False))
        max_items = int(args.get("max_items", 100))
        base = pathlib.Path(dir_path)
        if recursive:
            matches = list(base.rglob(pattern))
        else:
            matches = list(base.glob(pattern))
        items = []
        for p in matches[:max_items]:
            try:
                stat = p.stat()
                items.append({
                    "name": p.name,
                    "path": str(p),
                    "type": "dir" if p.is_dir() else "file",
                    "size_bytes": stat.st_size if p.is_file() else 0,
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })
            except Exception:
                items.append({"name": p.name, "path": str(p), "type": "unknown"})
        return {"path": dir_path, "count": len(items), "items": items}

    if name == "open_app":
        import subprocess
        app  = str(args.get("app", ""))
        app_args = str(args.get("args", ""))
        try:
            if sys.platform == "win32":
                if app_args:
                    subprocess.Popen([app] + app_args.split(), shell=True)
                else:
                    import os
                    os.startfile(app)
            else:
                subprocess.Popen([app] + (app_args.split() if app_args else []))
            return {"opened": app, "status": "launched"}
        except Exception as e:
            return {"opened": app, "status": "error", "error": str(e)}

    if name == "get_window_list":
        if sys.platform == "win32":
            try:
                import ctypes, ctypes.wintypes
                windows = []
                def _cb(hwnd, _):
                    if ctypes.windll.user32.IsWindowVisible(hwnd):
                        buf = ctypes.create_unicode_buffer(256)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
                        title = buf.value.strip()
                        if title:
                            windows.append({"hwnd": hwnd, "title": title})
                    return True
                CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                ctypes.windll.user32.EnumWindows(CB(_cb), 0)
                return {"windows": windows, "count": len(windows)}
            except Exception as e:
                return {"error": str(e), "windows": []}
        return {"error": "Only supported on Windows", "windows": []}

    if name == "focus_window":
        title_target = str(args.get("title", "")).lower()
        if sys.platform == "win32":
            try:
                import ctypes, ctypes.wintypes
                found = [None]
                def _cb(hwnd, _):
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
                    if title_target in buf.value.lower() and found[0] is None:
                        found[0] = hwnd
                    return True
                CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                ctypes.windll.user32.EnumWindows(CB(_cb), 0)
                if found[0]:
                    ctypes.windll.user32.ShowWindow(found[0], 9)   # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(found[0])
                    return {"focused": True, "hwnd": found[0]}
                return {"focused": False, "error": f"No window matching '{title_target}'"}
            except Exception as e:
                return {"focused": False, "error": str(e)}
        return {"focused": False, "error": "Only supported on Windows"}

    if name == "close_window":
        title_target = str(args.get("title", "")).lower()
        if sys.platform == "win32":
            try:
                import ctypes, ctypes.wintypes
                WM_CLOSE = 0x0010
                if not title_target:
                    hwnd = ctypes.windll.user32.GetForegroundWindow()
                    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                    return {"closed": True, "hwnd": hwnd}
                found = [None]
                def _cb(hwnd, _):
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
                    if title_target in buf.value.lower() and found[0] is None:
                        found[0] = hwnd
                    return True
                CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                ctypes.windll.user32.EnumWindows(CB(_cb), 0)
                if found[0]:
                    ctypes.windll.user32.PostMessageW(found[0], WM_CLOSE, 0, 0)
                    return {"closed": True, "hwnd": found[0]}
                return {"closed": False, "error": f"No window matching '{title_target}'"}
            except Exception as e:
                return {"closed": False, "error": str(e)}
        return {"closed": False, "error": "Only supported on Windows"}

    if name == "drag_and_drop":
        _require_pyautogui()
        sx, sy = int(args["start_x"]), int(args["start_y"])
        ex, ey = int(args["end_x"]),   int(args["end_y"])
        dur = float(args.get("duration", 0.5))
        pyautogui.moveTo(sx, sy, duration=0.2)
        pyautogui.dragTo(ex, ey, duration=dur, button="left")
        return {"dragged": {"from": (sx, sy), "to": (ex, ey)}}

    if name == "type_unicode":
        # Use clipboard bridge to input any Unicode text
        text = str(args.get("text", ""))
        ok = _set_clipboard_text(text)
        if not ok:
            # fallback: try pyautogui write for ASCII subset
            _require_pyautogui()
            pyautogui.typewrite(text, interval=0.03)
            return {"typed": text, "method": "typewrite_fallback"}
        time.sleep(0.1)
        _require_pyautogui()
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)
        return {"typed": text, "method": "clipboard_paste", "chars": len(text)}

    if name == "get_system_info":
        try:
            import psutil
            cpu  = psutil.cpu_percent(interval=1)
            mem  = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            boot = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
            procs = sorted(psutil.process_iter(["pid","name","cpu_percent","memory_info"]),
                           key=lambda p: p.info.get("cpu_percent") or 0, reverse=True)[:5]
            top_procs = []
            for p in procs:
                try:
                    top_procs.append({
                        "pid": p.info["pid"],
                        "name": p.info["name"],
                        "cpu_pct": round(p.info.get("cpu_percent") or 0, 1),
                        "mem_mb": round((p.info.get("memory_info") or type("x",[],{"rss":0})()).rss / 1024**2, 1),
                    })
                except Exception:
                    pass
            return {
                "cpu_percent": cpu,
                "memory": {"total_gb": round(mem.total/1024**3,1), "available_gb": round(mem.available/1024**3,1), "percent": mem.percent},
                "disk": {"total_gb": round(disk.total/1024**3,1), "free_gb": round(disk.free/1024**3,1), "percent": disk.percent},
                "boot_time": boot,
                "top_processes": top_procs,
            }
        except ImportError:
            # psutil not available — use run_shell fallback
            import subprocess
            out = subprocess.run(
                ["powershell","-NoProfile","-Command",
                 "Get-Process | Sort CPU -Desc | Select-Object -First 5 | Format-Table Name,CPU,WorkingSet -AutoSize | Out-String"],
                capture_output=True, text=True, timeout=15
            )
            return {"note": "psutil not installed; shell fallback", "output": out.stdout[:3000]}

    if name == "screenshot_region":
        _require_pyautogui()
        x, y = int(args["x"]), int(args["y"])
        w, h = int(args["width"]), int(args["height"])
        img = pyautogui.screenshot(region=(x, y, w, h))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"screenshot_b64": b64, "region": {"x":x,"y":y,"width":w,"height":h}}

    if name == "set_window_position":
        title_t = str(args.get("title","")).lower()
        if sys.platform == "win32":
            try:
                import ctypes, ctypes.wintypes
                found = [None]
                def _cb(hwnd, _):
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
                    if title_t in buf.value.lower() and found[0] is None:
                        found[0] = hwnd
                    return True
                CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                ctypes.windll.user32.EnumWindows(CB(_cb), 0)
                if not found[0]:
                    return {"moved": False, "error": f"No window matching '{title_t}'"}
                # Get current rect
                import ctypes.wintypes as wt
                rc = wt.RECT()
                ctypes.windll.user32.GetWindowRect(found[0], ctypes.byref(rc))
                nx = args.get("x", rc.left)
                ny = args.get("y", rc.top)
                nw = args.get("width",  rc.right  - rc.left)
                nh = args.get("height", rc.bottom - rc.top)
                ctypes.windll.user32.MoveWindow(found[0], int(nx), int(ny), int(nw), int(nh), True)
                return {"moved": True, "position": {"x":nx,"y":ny,"width":nw,"height":nh}}
            except Exception as e:
                return {"moved": False, "error": str(e)}
        return {"moved": False, "error": "Only supported on Windows"}

    if name == "get_process_list":
        try:
            import psutil
            sort_by = str(args.get("sort_by", "cpu")).lower()
            top_n   = int(args.get("top_n", 10))
            key_fn  = (lambda p: p.info.get("cpu_percent") or 0) if sort_by == "cpu" \
                      else (lambda p: (p.info.get("memory_info") or type("x",[],{"rss":0})()).rss)
            procs = sorted(psutil.process_iter(["pid","name","cpu_percent","memory_info","status"]),
                           key=key_fn, reverse=True)[:top_n]
            result = []
            for p in procs:
                try:
                    mem = p.info.get("memory_info")
                    result.append({
                        "pid":    p.info["pid"],
                        "name":   p.info["name"],
                        "cpu_pct":round(p.info.get("cpu_percent") or 0, 1),
                        "mem_mb": round(mem.rss/1024**2, 1) if mem else 0,
                        "status": p.info.get("status",""),
                    })
                except Exception:
                    pass
            return {"processes": result, "count": len(result), "sorted_by": sort_by}
        except ImportError:
            r = _dispatch("run_shell", {"command": "Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 | Format-Table -AutoSize | Out-String"})
            return {"note": "psutil not available", "output": r.get("output","")}

    if name == "kill_process":
        import signal
        proc_name = args.get("name","")
        proc_pid  = args.get("pid")
        try:
            import psutil
            killed = []
            for p in psutil.process_iter(["pid","name"]):
                if (proc_pid and p.info["pid"] == int(proc_pid)) or \
                   (proc_name and proc_name.lower() in p.info["name"].lower()):
                    p.terminate()
                    killed.append({"pid": p.info["pid"], "name": p.info["name"]})
            return {"killed": killed, "count": len(killed)}
        except ImportError:
            cmd = f"Stop-Process -Name '{proc_name}' -Force" if proc_name \
                  else f"Stop-Process -Id {proc_pid} -Force"
            return _dispatch("run_shell", {"command": cmd})

    if name == "download_file":
        try:
            import httpx
            url       = str(args["url"])
            save_path = str(args["save_path"])
            timeout   = int(args.get("timeout", 60))
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                pathlib.Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                pathlib.Path(save_path).write_bytes(resp.content)
            return {"downloaded": True, "path": save_path, "bytes": len(resp.content), "status": resp.status_code}
        except Exception as e:
            return {"downloaded": False, "error": str(e)}

    if name == "zip_files":
        import zipfile
        paths  = args.get("paths", [])
        output = str(args["output"])
        added  = []
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in paths:
                pp = pathlib.Path(p)
                if pp.is_dir():
                    for f in pp.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(pp.parent))
                            added.append(str(f))
                elif pp.is_file():
                    zf.write(pp, pp.name)
                    added.append(str(pp))
        return {"zipped": output, "files_added": len(added), "paths": added[:20]}

    if name == "get_active_window_title":
        if sys.platform == "win32":
            try:
                import ctypes
                buf = ctypes.create_unicode_buffer(512)
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                return {"title": buf.value, "hwnd": hwnd}
            except Exception as e:
                return {"title": "", "error": str(e)}
        return {"title": "", "error": "Only supported on Windows"}

    # ── AI-generated custom tools (hot-reloadable) ────────────────
    # ── AI-generated custom tools (hot-reloadable) ────────────────
    if name in _CUSTOM_DISPATCH:
        return _CUSTOM_DISPATCH[name](args)

    raise NotImplementedError(f"_dispatch: unhandled tool {name!r}")


def _require_pyautogui():
    if not _PYAUTOGUI_AVAILABLE:
        raise RuntimeError(
            "pyautogui not installed. Run: pip install pyautogui pillow"
        )

    if name == "kill_process":
        proc_name = str(args.get("name",""))
        proc_pid  = args.get("pid")
        try:
            import psutil
            killed = []
            for p in psutil.process_iter(["pid","name"]):
                if (proc_pid and p.info["pid"] == int(proc_pid)) or \
                   (proc_name and proc_name.lower() in p.info["name"].lower()):
                    p.terminate()
                    killed.append({"pid": p.info["pid"], "name": p.info["name"]})
            return {"killed": killed, "count": len(killed)}
        except ImportError:
            cmd = f"Stop-Process -Name '{proc_name}' -Force" if proc_name \
                  else f"Stop-Process -Id {proc_pid} -Force"
            return _dispatch("run_shell", {"command": cmd})

    if name == "download_file":
        try:
            import httpx
            url       = str(args["url"])
            save_path = str(args["save_path"])
            timeout   = int(args.get("timeout", 60))
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                pathlib.Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                pathlib.Path(save_path).write_bytes(resp.content)
            return {"downloaded": True, "path": save_path,
                    "bytes": len(resp.content), "status": resp.status_code}
        except Exception as e:
            return {"downloaded": False, "error": str(e)}

    if name == "zip_files":
        import zipfile
        paths  = args.get("paths", [])
        output = str(args["output"])
        added  = []
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in paths:
                pp = pathlib.Path(p)
                if pp.is_dir():
                    for f in pp.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(pp.parent))
                            added.append(str(f))
                elif pp.is_file():
                    zf.write(pp, pp.name)
                    added.append(str(pp))
        return {"zipped": output, "files_added": len(added), "paths": added[:20]}

    if name == "get_active_window_title":
        if sys.platform == "win32":
            try:
                import ctypes
                buf  = ctypes.create_unicode_buffer(512)
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                return {"title": buf.value, "hwnd": hwnd}
            except Exception as e:
                return {"title": "", "error": str(e)}
        return {"title": "", "error": "Only supported on Windows"}

    # ── AI-generated custom tools (hot-reloadable) ────────────────
    if name in _CUSTOM_DISPATCH:
        return _CUSTOM_DISPATCH[name](args)

    raise NotImplementedError(f"_dispatch: unhandled tool {name!r}")


def _require_pyautogui():
    if not _PYAUTOGUI_AVAILABLE:
        raise RuntimeError(
            "pyautogui not installed. Run: pip install pyautogui pillow"
        )


# ──────────────────────

# -----------------------------------------------------------------
# Module init -- load AI-generated custom tools on import
# -----------------------------------------------------------------
try:
    _load_custom_tools()
except Exception as _init_e:
    import logging as _logging
    _logging.getLogger(__name__).warning("custom_tools init failed: %s", _init_e)
