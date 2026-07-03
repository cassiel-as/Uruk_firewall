"""
URUK App Controller — Windows desktop app automation (v8.47)

Controls desktop apps via UI Automation (pywinauto) or ctypes + clipboard
fallback. The FastAPI process and the target apps share the same Windows
desktop session, so server-side code can drive the UI directly.

Public API
----------
  list_apps()                             -> List[dict]
  launch_app(app_key)                     -> dict
  await send_to_app(app_key, message)     -> dict
  get_deps_status()                       -> dict
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.relay_protocol import (
    format_chatgpt_relay_message as _protocol_format_chatgpt_relay_message,
    format_codex_relay_message as _protocol_format_codex_relay_message,
    format_relay_message as _protocol_format_relay_message,
    infer_relay_mode as _protocol_infer_relay_mode,
)

# ── psutil (process detection) ────────────────────────────────────
try:
    import psutil as _psutil
    _PS_OK = True
except ImportError:
    _psutil = None   # type: ignore
    _PS_OK = False

# ── pywinauto (primary automation) ───────────────────────────────
try:
    from pywinauto import Application as _PWApp  # type: ignore
    from pywinauto.keyboard import send_keys as _pw_send_keys  # type: ignore
    _PW_OK = True
except Exception:
    _PWApp = None   # type: ignore
    _pw_send_keys = None  # type: ignore
    _PW_OK = False

# ── Known controllable apps ───────────────────────────────────────
_LOCAL = Path(os.environ.get("LOCALAPPDATA", "C:/Users/Public"))
_PROGRAMS = Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
_PROGRAMS_X86 = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))

_KNOWN_APPS: Dict[str, Dict[str, Any]] = {
    "claude": {
        "display": "Claude Desktop",
        "icon": "🤖",
        "process_names": ["Claude.exe", "claude.exe"],
        "window_title": "Claude",
        "new_conversation_hotkey": "^n",
        "exe_candidates": [
            _LOCAL / "AnthropicClaude" / "claude.exe",
            _LOCAL / "Programs" / "claude" / "Claude.exe",
            _LOCAL / "Programs" / "AnthropicClaude" / "Claude.exe",
            Path("C:/Users") / os.environ.get("USERNAME", "user") / "AppData" / "Local" / "AnthropicClaude" / "claude.exe",
        ],
    },
    "chatgpt": {
        "display": "ChatGPT Desktop",
        "icon": "💬",
        "process_names": ["ChatGPT.exe", "chatgpt.exe"],
        "window_title": "ChatGPT",
        "exe_candidates": [
            _LOCAL / "Programs" / "chatgpt" / "ChatGPT.exe",
        ],
    },
    "copilot": {
        "display": "Windows Copilot",
        "icon": "CP",
        "process_names": ["mscopilot.exe", "mscopilot_proxy.exe"],
        "window_title": "Copilot",
        "app_id": "Microsoft.Copilot_8wekyb3d8bbwe!App",
        "exe_candidates": [
            _PROGRAMS_X86 / "Microsoft" / "Copilot" / "Application" / "mscopilot.exe",
            _PROGRAMS_X86 / "Microsoft" / "Copilot" / "Application" / "mscopilot_proxy.exe",
            _PROGRAMS_X86 / "Microsoft" / "Edge" / "Application" / "mscopilot.exe",
        ],
        "capabilities": [
            "windows_context",
            "copilot_vision",
            "file_search",
            "screenshot_review",
            "windows_settings_guidance",
        ],
    },
    "codex": {
        "display": "Codex",
        "icon": "CX",
        "process_names": [
            "Codex.exe",
            "codex.exe",
            "codex-command-runner.exe",
            "codex-command-runner-0.135.0-alpha.1.exe",
        ],
        "window_title": "Codex",
        "new_conversation_hotkey": "^n",
        "exe_candidates": [
            _LOCAL / "Programs" / "codex" / "Codex.exe",
            _LOCAL / "Codex" / "Codex.exe",
            Path("C:/Program Files/Codex/Codex.exe"),
        ],
    },
    "claude_code": {
        "display": "Claude Code",
        "icon": "⌨️",
        # Claude Code runs inside a terminal (cmd / PowerShell / Windows Terminal)
        # We detect by looking for 'claude' process spawned from a terminal.
        "process_names": ["claude.exe", "node.exe"],
        "window_title": "Claude",   # terminal title often contains "Claude"
        "exe_candidates": [
            # npm global install
            Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
            Path(os.environ.get("APPDATA", "")) / "npm" / "claude",
            # winget / scoop install
            Path("C:/Program Files/Claude Code/claude.exe"),
        ],
        # Claude Code is terminal-based — send via clipboard → Ctrl+V → Enter
        "send_strategy": "terminal_paste",
    },
    "cowork": {
        "display": "Claude Cowork",
        "icon": "🤝",
        # Cowork is just Claude Desktop in a special mode — same process
        "process_names": ["Claude.exe", "claude.exe"],
        "window_title": "Claude",
        "new_conversation_hotkey": "^n",
        "exe_candidates": [
            _LOCAL / "AnthropicClaude" / "claude.exe",
        ],
        # Alias for "claude" — same send logic
        "alias": "claude",
    },
}

def infer_codex_relay_mode(message: str, relay_mode: Optional[str] = None) -> str:
    """Infer which Codex relay instruction set should wrap this request."""
    return _protocol_infer_relay_mode(message, relay_mode)


def _format_codex_relay_message(message: str, relay_mode: Optional[str] = None) -> str:
    return _protocol_format_codex_relay_message(message, relay_mode)


# ─────────────────────────────────────────────────────────────────
# Dep status
# ─────────────────────────────────────────────────────────────────

def get_deps_status() -> dict:
    return {
        "pywinauto": _PW_OK,
        "psutil":    _PS_OK,
        "platform":  sys.platform,
        "is_windows": sys.platform == "win32",
    }


# ─────────────────────────────────────────────────────────────────
# Process detection
# ─────────────────────────────────────────────────────────────────

def _is_running(process_names: List[str]) -> bool:
    names_lower = [n.lower() for n in process_names]
    if _PS_OK and _psutil:
        try:
            for p in _psutil.process_iter(["name"]):
                if p.info["name"] and p.info["name"].lower() in names_lower:
                    return True
            return False
        except Exception:
            pass
    # Fallback: tasklist (Windows only)
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"],
                text=True, stderr=subprocess.DEVNULL,
            )
            return any(name.lower() in out.lower() for name in names_lower)
        except Exception:
            pass
    return False


def _find_claude_code_exe() -> Optional[Path]:
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude",
        Path("C:/Program Files/Claude Code/claude.exe"),
    ]
    root = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code"
    if root.exists():
        candidates.extend(
            sorted(root.glob("*/claude.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
        )
    for path in candidates:
        try:
            if path.exists():
                return path
        except Exception:
            continue
    return None


def _find_codex_cli_exe() -> Optional[Path]:
    candidates: List[Path] = []
    bin_root = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    if bin_root.exists():
        candidates.extend(
            sorted(bin_root.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
        )
    try:
        import shutil
        found = shutil.which("codex")
        if found:
            candidates.append(Path(found))
    except Exception:
        pass
    for path in candidates:
        try:
            if path.exists():
                return path
        except Exception:
            continue
    return None


def _is_claude_code_available() -> bool:
    return _find_claude_code_exe() is not None


def _is_claude_code_running() -> bool:
    if not (_PS_OK and _psutil):
        return _is_claude_code_available()
    try:
        for p in _psutil.process_iter(["name", "cmdline", "exe"]):
            name = (p.info.get("name") or "").lower()
            if name not in {"claude.exe", "claude"}:
                continue
            cmd = " ".join(p.info.get("cmdline") or [])
            exe = str(p.info.get("exe") or "")
            if "claude-code" in cmd.lower() or "claude-code" in exe.lower():
                return True
    except Exception:
        pass
    return _is_claude_code_available()


# ─────────────────────────────────────────────────────────────────
# Public: list apps
# ─────────────────────────────────────────────────────────────────

def list_apps() -> List[dict]:
    result = []
    for key, cfg in _KNOWN_APPS.items():
        if key == "claude_code":
            launchable = _is_claude_code_available()
            running = _is_claude_code_running()
        else:
            running = _is_running(cfg["process_names"])
            launchable = any(Path(p).exists() for p in cfg["exe_candidates"]) or bool(cfg.get("app_id"))
        result.append({
            "key":       key,
            "display":   cfg["display"],
            "icon":      cfg["icon"],
            "running":   running,
            "launchable": launchable,
            "capabilities": cfg.get("capabilities", []),
        })
    return result


# ─────────────────────────────────────────────────────────────────
# Public: launch app
# ─────────────────────────────────────────────────────────────────

def launch_app(app_key: str) -> dict:
    cfg = _KNOWN_APPS.get(app_key)
    if not cfg:
        return {"ok": False, "error": f"Unknown app: {app_key}"}
    if app_key == "claude_code":
        exe = _find_claude_code_exe()
        if not exe:
            return {"ok": False, "error": "Claude Code executable not found."}
        subprocess.Popen([str(exe)], shell=False)
        return {"ok": True, "message": "Launched Claude Code. Give it a moment to open."}
    if _is_running(cfg["process_names"]):
        return {"ok": True, "message": f"{cfg['display']} is already running."}
    for exe in cfg["exe_candidates"]:
        if Path(exe).exists():
            subprocess.Popen([str(exe)], shell=False)
            return {"ok": True, "message": f"Launched {cfg['display']}. Give it a moment to open."}
    if cfg.get("app_id"):
        subprocess.Popen(
            ["explorer.exe", f"shell:appsFolder\\{cfg['app_id']}"],
            shell=False,
        )
        return {"ok": True, "message": f"Launched {cfg['display']} via Start app id. Give it a moment to open."}
    return {"ok": False, "error": f"{cfg['display']} not found. Is it installed?"}


# ─────────────────────────────────────────────────────────────────
# Windows clipboard via ctypes (no pyperclip needed)
# ─────────────────────────────────────────────────────────────────

def _set_clipboard(text: str) -> None:
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE  = 0x0002
    user32  = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    encoded = (text + "\x00").encode("utf-16-le")

    user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
    user32.OpenClipboard.restype = ctypes.wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = ctypes.wintypes.BOOL
    user32.SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
    user32.SetClipboardData.restype = ctypes.wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL

    if not user32.OpenClipboard(None):
        raise OSError("OpenClipboard failed")
    try:
        if not user32.EmptyClipboard():
            raise OSError("EmptyClipboard failed")
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
        if not h:
            raise OSError("GlobalAlloc failed")
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            raise OSError("GlobalLock failed")
        ctypes.memmove(ptr, encoded, len(encoded))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            raise OSError("SetClipboardData failed")
        # Clipboard owns h after successful SetClipboardData.
    finally:
        user32.CloseClipboard()


# ─────────────────────────────────────────────────────────────────
# Window focus via ctypes
# ─────────────────────────────────────────────────────────────────

def _focus_window(title_contains: str) -> Optional[int]:
    """Bring window whose title contains `title_contains` to foreground.
    Returns hwnd on success, None on failure.

    Searches both visible AND non-visible windows (Electron/UWP apps like
    ChatGPT Desktop report IsWindowVisible=False when minimised or backgrounded).
    SW_RESTORE is always called to un-minimise before returning.
    """
    user32 = ctypes.windll.user32
    found_visible: List[int] = []
    found_any: List[int] = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM,
    )

    def _cb(hwnd: int, _: int) -> bool:
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_contains.lower() in buf.value.lower():
                if user32.IsWindowVisible(hwnd):
                    found_visible.append(hwnd)
                    return False  # stop at first visible match
                else:
                    found_any.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    hwnd = (found_visible or found_any or [None])[0]
    if not hwnd:
        return None
    user32.ShowWindow(hwnd, 9)         # SW_RESTORE — un-minimise / make visible
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.35)
    return hwnd


# ─────────────────────────────────────────────────────────────────
# Send via pywinauto (primary path)
# ─────────────────────────────────────────────────────────────────

def _send_pywinauto(cfg: dict, message: str) -> dict:
    title = cfg["window_title"]
    try:
        pw_app = _PWApp(backend="uia").connect(
            title_re=f".*{title}.*", timeout=5
        )
        win = pw_app.window(title_re=f".*{title}.*")
        win.restore()
        win.set_focus()
        time.sleep(0.4)

        # Try to find the input element (Claude uses a contenteditable Document)
        _input_found = False
        for ctrl_type in ("Document", "Edit", "Text"):
            try:
                el = win.child_window(control_type=ctrl_type, found_index=0)
                el.click_input()
                _input_found = True
                break
            except Exception:
                continue

        if not _input_found:
            # Click near the bottom-centre of the window (typical input location)
            rect = win.rectangle()
            cx = (rect.right - rect.left) // 2
            cy = (rect.bottom - rect.top) - 80
            win.click_input(coords=(cx, cy))

        # Do not type arbitrary relay prompts through pywinauto.send_keys().
        # send_keys treats {...} as special key/repetition syntax, so JSON,
        # tool templates, and UPGRADE_EXECUTION_PLAN blocks can raise errors
        # such as "invalid repetition count required". Use the clipboard for
        # body text and keep send_keys only for simple control chords.
        time.sleep(0.2)
        _set_clipboard(message)
        time.sleep(0.1)
        _pw_send_keys("^v")
        time.sleep(0.1)
        _pw_send_keys("{ENTER}")
        return {"ok": True, "method": "pywinauto_clipboard", "message": "Sent."}
    except Exception as e:
        return {"ok": False, "error": f"pywinauto: {e}"}


# ─────────────────────────────────────────────────────────────────
# Send via ctypes + clipboard (fallback path)
# ─────────────────────────────────────────────────────────────────

def _send_ctypes(cfg: dict, message: str) -> dict:
    if sys.platform != "win32":
        return {"ok": False, "error": "App control requires Windows."}
    try:
        _set_clipboard(message)
        time.sleep(0.15)
        hwnd = _focus_window(cfg["window_title"])
        if not hwnd:
            return {"ok": False, "error": f"Window '{cfg['window_title']}' not found."}

        user32 = ctypes.windll.user32
        VK_CONTROL  = 0x11
        VK_V        = 0x56
        VK_RETURN   = 0x0D
        KEYUP       = 0x0002

        # Ctrl+V — paste
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.06)
        user32.keybd_event(VK_V, 0, KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYUP, 0)
        time.sleep(0.18)

        # Enter — send
        user32.keybd_event(VK_RETURN, 0, 0, 0)
        time.sleep(0.06)
        user32.keybd_event(VK_RETURN, 0, KEYUP, 0)

        return {"ok": True, "method": "ctypes+clipboard", "message": "Sent."}
    except Exception as e:
        return {"ok": False, "error": f"ctypes: {e}"}


def _start_new_conversation(cfg: dict) -> dict:
    """Best-effort new chat isolation before sending a relay request."""
    hotkey = cfg.get("new_conversation_hotkey")
    if not hotkey:
        return {"ok": True, "skipped": True, "message": "No new conversation hotkey configured."}
    if sys.platform != "win32":
        return {"ok": False, "error": "New conversation hotkey is Windows-only."}

    # Primary: pywinauto can target the app window before sending Ctrl+N.
    if _PW_OK:
        try:
            title = cfg["window_title"]
            pw_app = _PWApp(backend="uia").connect(title_re=f".*{title}.*", timeout=5)
            win = pw_app.window(title_re=f".*{title}.*")
            win.set_focus()
            time.sleep(0.15)
            _pw_send_keys(hotkey)
            time.sleep(0.9)
            return {"ok": True, "method": "pywinauto_hotkey", "hotkey": hotkey}
        except Exception:
            pass

    # Fallback: ctypes Ctrl+N only. Other hotkeys should fail closed.
    if hotkey != "^n":
        return {"ok": False, "error": f"No ctypes fallback for hotkey {hotkey!r}"}
    try:
        hwnd = _focus_window(cfg["window_title"])
        if not hwnd:
            return {"ok": False, "error": f"Window '{cfg['window_title']}' not found."}

        user32 = ctypes.windll.user32
        VK_CONTROL = 0x11
        VK_N = 0x4E
        KEYUP = 0x0002

        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_N, 0, 0, 0)
        time.sleep(0.06)
        user32.keybd_event(VK_N, 0, KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYUP, 0)
        time.sleep(0.9)
        return {"ok": True, "method": "ctypes_hotkey", "hotkey": hotkey}
    except Exception as e:
        return {"ok": False, "error": f"new conversation: {e}"}


# ─────────────────────────────────────────────────────────────────
# Public: send message to app
# ─────────────────────────────────────────────────────────────────

async def send_to_app(app_key: str, message: str, new_conversation: bool = False) -> dict:
    cfg = _KNOWN_APPS.get(app_key)
    if not cfg:
        return {"ok": False, "error": f"Unknown app: {app_key}"}
    if not _is_running(cfg["process_names"]):
        return {"ok": False, "error": f"{cfg['display']} is not running. Launch it first."}
    if sys.platform != "win32":
        return {"ok": False, "error": "App control is Windows-only."}

    new_chat_result = None
    if new_conversation:
        new_chat_result = await asyncio.to_thread(_start_new_conversation, cfg)
        if not new_chat_result.get("ok"):
            return new_chat_result

    if _PW_OK:
        result = await asyncio.to_thread(_send_pywinauto, cfg, message)
        if result["ok"]:
            if new_chat_result:
                result["new_conversation"] = new_chat_result
            return result
        # Fall through to ctypes if pywinauto fails

    result = await asyncio.to_thread(_send_ctypes, cfg, message)
    if result.get("ok") and new_chat_result:
        result["new_conversation"] = new_chat_result
    return result


# ─────────────────────────────────────────────────────────────────
# Response reading via UIA (pywinauto)
# ─────────────────────────────────────────────────────────────────

def _uia_text_snapshot(win) -> str:
    """
    Collect all visible text from a pywinauto window via UIA.
    Walks the first 6 levels of the accessibility tree and concatenates
    non-empty name/value strings, skipping duplicates.
    """
    seen: set = set()
    parts: List[str] = []

    def _walk(el, depth: int = 0) -> None:
        if depth > 6:
            return
        try:
            txt = (el.window_text() or "").strip()
            if txt and txt not in seen and len(txt) > 1:
                seen.add(txt)
                parts.append(txt)
        except Exception:
            pass
        try:
            for child in el.children():
                _walk(child, depth + 1)
        except Exception:
            pass

    try:
        _walk(win.wrapper_object())
    except Exception:
        pass
    return "\n".join(parts)


def _has_stop_button(win) -> bool:
    """Return True if Claude Desktop is still generating (Stop button visible)."""
    try:
        # Claude Desktop shows a button titled "Stop" or "Stop generating"
        for ctrl_type in ("Button",):
            try:
                btns = win.children(control_type=ctrl_type)
                for b in btns:
                    name = (b.window_text() or "").lower()
                    if "stop" in name:
                        return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _extract_response_after_user_msg(full_text: str, user_msg: str) -> str:
    """
    Find `user_msg` in `full_text` and return everything after it,
    trimmed of leading whitespace / UI chrome.
    Falls back to returning the tail of the text if message not found.

    Priority 1: structured relay tag after the sent message.
    Priority 2: Diff-based extraction (find user_msg, take what follows).
    Priority 3: Last 30% of text.
    """
    import re as _re

    idx = full_text.find(user_msg)
    tag_search_text = full_text[idx + len(user_msg):] if idx != -1 else full_text

    # ── Priority 1: relay structured response ─────────────────────
    matches = _re.findall(r"<CODEX_RESPONSE>(.*?)</CODEX_RESPONSE>", tag_search_text, _re.DOTALL)
    if matches:
        return matches[-1].strip()

    matches = _re.findall(r"<URUK_RESPONSE>(.*?)</URUK_RESPONSE>", tag_search_text, _re.DOTALL)
    if matches:
        return matches[-1].strip()

    # ── Priority 2: find user message boundary ─────────────────────
    if idx != -1:
        tail = full_text[idx + len(user_msg):].strip()
        # Remove common UI labels that appear between message and response
        _skip = ("Copy", "Retry", "Edit", "Like", "Dislike", "Stop", "You", "Claude")
        lines = [ln for ln in tail.splitlines() if ln.strip() not in _skip]
        return "\n".join(lines).strip()

    # ── Priority 3: last 30% of the text ──────────────────────────
    chars = len(full_text)
    return full_text[int(chars * 0.7):].strip()


def _poll_and_read(cfg: dict, sent_message: str, timeout: float) -> dict:
    """
    After message is sent, poll the UIA tree until response is stable.
    Returns {ok, response, method}.
    """
    title = cfg["window_title"]
    try:
        pw_app = _PWApp(backend="uia").connect(title_re=f".*{title}.*", timeout=6)
        win = pw_app.window(title_re=f".*{title}.*")

        # Baseline snapshot BEFORE the response comes in
        # (we already sent the message, so wait 1s then baseline)
        time.sleep(1.5)
        baseline = _uia_text_snapshot(win)

        # Poll: wait until stop button is gone AND text is stable
        deadline = time.time() + timeout
        prev_text = baseline
        stable_ticks = 0

        while time.time() < deadline:
            time.sleep(1.2)

            generating = _has_stop_button(win)
            current = _uia_text_snapshot(win)

            if current == prev_text:
                stable_ticks += 1
                # If not generating and stable for 2 ticks → done
                if not generating and stable_ticks >= 2:
                    break
                # If still generating, keep waiting
            else:
                stable_ticks = 0
                prev_text = current

        final_text = prev_text

        # Extract only the new portion (response)
        response = _extract_response_after_user_msg(final_text, sent_message)
        if not response:
            # diff approach: new chars vs baseline
            new_chars = final_text.replace(baseline, "", 1).strip()
            response = new_chars or final_text[-1500:].strip()

        return {"ok": True, "response": response, "method": "uia_poll"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def _read_clipboard_now() -> str:
    """Read current clipboard text immediately, no waiting."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        CF_UNICODETEXT = 13
        user32.OpenClipboard(0)
        h = user32.GetClipboardData(CF_UNICODETEXT)
        user32.CloseClipboard()
        if h:
            ptr = kernel32.GlobalLock(h)
            size = kernel32.GlobalSize(h) // 2
            buf = (ctypes.c_wchar * size)()
            ctypes.memmove(buf, ptr, size * 2)
            kernel32.GlobalUnlock(h)
            return buf.value.strip()
    except Exception:
        pass
    return ""


def _chatgpt_active_copy(cfg: dict) -> bool:
    """
    Actively copy ChatGPT's last response to clipboard.
    Strategy 1: click the last visible "Copy" button in the UIA tree.
    Strategy 2: Ctrl+C on the focused window (copies selected text).
    Returns True if a copy action was attempted.
    """
    title = cfg.get("window_title", "ChatGPT")
    try:
        hwnd = _focus_window(title)
        if not hwnd:
            return False
        time.sleep(0.3)

        # Strategy 1: pywinauto — find the last "Copy" button in conversation
        if _PW_OK:
            try:
                pw_app = _PWApp(backend="uia").connect(
                    title_re=f".*{title}.*", timeout=3
                )
                win = pw_app.window(title_re=f".*{title}.*")
                btns = []
                for ctrl_type in ("Button",):
                    try:
                        for b in win.children(control_type=ctrl_type):
                            name = (b.window_text() or b.automation_id() or "").lower()
                            if "copy" in name:
                                btns.append(b)
                    except Exception:
                        pass
                if btns:
                    btns[-1].click_input()  # last Copy button = most recent response
                    time.sleep(0.3)
                    return True
            except Exception:
                pass

        # Strategy 2: send Ctrl+C to copy selected / focused text
        user32 = ctypes.windll.user32
        VK_CONTROL, VK_C, KEYUP = 0x11, 0x43, 0x0002
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_C, 0, 0, 0)
        time.sleep(0.06)
        user32.keybd_event(VK_C, 0, KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYUP, 0)
        return True
    except Exception:
        return False


def _clipboard_read_response(cfg: dict, timeout: float) -> dict:
    """
    Fallback: after waiting `timeout` seconds, try to read clipboard.
    User or automation must have copied the response text already.
    """
    time.sleep(min(timeout, 30))
    try:
        text = _read_clipboard_now()
        if text:
            return {"ok": True, "response": text, "method": "clipboard_read"}
    except Exception:
        pass


def _call_claude_code_cli(message: str, timeout: float) -> dict:
    """Call Claude Code directly in print mode. Used by the UI's Claude Code relay."""
    exe = _find_claude_code_exe()
    if not exe:
        return {"ok": False, "error": "Claude Code executable not found."}

    cmd = [
        str(exe),
        "-p",
        message,
        "--output-format",
        "text",
        "--permission-mode",
        "plan",
        "--tools",
        "Read,Glob,Grep",
        "--no-session-persistence",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(10.0, timeout),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Claude Code timed out after {timeout:.0f}s"}
    except Exception as e:
        return {"ok": False, "error": f"Claude Code launch failed: {type(e).__name__}: {e}"}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": f"Claude Code exited {proc.returncode}: {stderr or stdout[:1000]}",
            "method": "claude_code_cli",
        }
    if not stdout:
        return {
            "ok": False,
            "error": f"Claude Code returned empty output. stderr={stderr[:1000]}",
            "method": "claude_code_cli",
        }
    return {
        "ok": True,
        "response": stdout,
        "stderr": stderr[:1000],
        "method": "claude_code_cli",
    }


def _call_codex_cli(message: str, timeout: float) -> dict:
    """Call Codex CLI non-interactively. Used by the UI's Codex relay."""
    exe = _find_codex_cli_exe()
    if not exe:
        return {"ok": False, "error": "Codex CLI executable not found."}

    out_dir = Path.cwd() / "data" / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"codex-relay-{int(time.time() * 1000)}.txt"
    cmd = [
        str(exe),
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "-C",
        str(Path.cwd()),
        "-o",
        str(out_path),
        "--color",
        "never",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=message,
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(10.0, timeout),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Codex CLI timed out after {timeout:.0f}s"}
    except Exception as e:
        return {"ok": False, "error": f"Codex CLI launch failed: {type(e).__name__}: {e}"}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    response = ""
    try:
        if out_path.exists():
            response = out_path.read_text(encoding="utf-8").strip()
    except Exception:
        response = ""
    if not response:
        response = stdout

    if proc.returncode != 0:
        return {
            "ok": False,
            "error": f"Codex CLI exited {proc.returncode}: {stderr or stdout[:1000]}",
            "method": "codex_cli",
            "stdout": stdout[:2000],
            "stderr": stderr[:2000],
        }
    if not response:
        return {
            "ok": False,
            "error": f"Codex CLI returned empty output. stderr={stderr[:1000]}",
            "method": "codex_cli",
        }
    return {
        "ok": True,
        "response": response,
        "stdout": stdout[:2000],
        "stderr": stderr[:2000],
        "output_path": str(out_path),
        "method": "codex_cli",
    }

# -----------------------------------------------------------------
# Dependency installer
# -----------------------------------------------------------------

def install_deps() -> dict:
    """Install missing automation deps in the current Python environment."""
    needed = []
    if not _PW_OK:
        needed.append("pywinauto")
    if not _PS_OK:
        needed.append("psutil")
    if not needed:
        return {"ok": True, "message": "All deps already installed."}
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + needed,
            timeout=120,
        )
        return {"ok": True, "message": f"Installed: {', '.join(needed)}. Restart server to activate."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────
# Claude Code — subprocess non-interactive mode
# claude -p "<prompt>" returns response to stdout directly,
# bypassing terminal UI injection entirely.
# ─
def _send_claude_code_subprocess(message: str, timeout: float = 120.0) -> dict:
    """Run claude -p non-interactively, bypassing terminal UI injection."""
    result = _call_claude_code_cli(message, timeout)
    if result.get("ok"):
        result["method"] = "claude_code_subprocess"
    return result


def _find_chatgpt_hwnd() -> Optional[int]:
    """Find the main ChatGPT Desktop window handle by matching process PIDs.

    ChatGPT Desktop (Electron) often changes its window title to show the current
    conversation name, so title-based search is unreliable.  Instead we enumerate
    all windows, filter by PID (any ChatGPT.exe process), and pick the largest one
    — which is always the main UI window.
    """
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32

    # Collect ChatGPT process IDs
    chatgpt_pids: set = set()
    try:
        if _psutil:
            for p in _psutil.process_iter(["name", "pid"]):
                if p.info.get("name", "") and "chatgpt" in p.info["name"].lower():
                    chatgpt_pids.add(p.info["pid"])
    except Exception:
        pass

    if not chatgpt_pids:
        return None

    found: List = []   # (hwnd, area)

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )

    def _cb(hwnd: int, _: int) -> bool:
        # Check PID ownership
        pid = ctypes.wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in chatgpt_pids:
            return True
        # Require a reasonably sized window (skip renderer/background windows)
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w > 300 and h > 300:
            found.append((hwnd, w * h))
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    if not found:
        return None
    found.sort(key=lambda x: x[1], reverse=True)
    return found[0][0]


def _chatgpt_find_input_center_uia(hwnd: int) -> Optional[tuple[int, int]]:
    """Find ChatGPT's message input through UI Automation."""
    if not _PW_OK:
        return None
    try:
        import pywinauto as _pw

        app = _pw.Application(backend="uia").connect(handle=hwnd, timeout=5)
        win = app.window(handle=hwnd)
        candidates: List[tuple[int, int, int, int]] = []
        for ctrl in win.descendants():
            try:
                if ctrl.element_info.control_type != "Edit":
                    continue
                name = (ctrl.window_text() or "").strip()
                rect = ctrl.rectangle()
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width < 120 or height < 20:
                    continue
                if name and not any(marker in name for marker in ("想問", "Message", "Ask", "Send")):
                    continue
                candidates.append((rect.left, rect.top, rect.right, rect.bottom))
            except Exception:
                continue
        if not candidates:
            return None
        # The prompt box is the lowest visible edit control.
        left, top, right, bottom = max(candidates, key=lambda r: r[1])
        return (left + right) // 2, (top + bottom) // 2
    except Exception:
        return None


def _chatgpt_start_new_conversation(hwnd: int) -> bool:
    """Open a fresh ChatGPT conversation when the caller requested isolation."""
    user32 = ctypes.windll.user32
    try:
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
    except Exception:
        pass

    if _PW_OK:
        try:
            import pywinauto as _pw

            app = _pw.Application(backend="uia").connect(handle=hwnd, timeout=5)
            win = app.window(handle=hwnd)
            for ctrl in win.descendants():
                try:
                    name = (ctrl.window_text() or "").strip()
                    ctype = ctrl.element_info.control_type
                    if name in {"新對話", "New chat"} and ctype in {"Button", "Hyperlink", "ListItem"}:
                        try:
                            ctrl.invoke()
                        except Exception:
                            ctrl.click_input()
                        time.sleep(1.0)
                        return _chatgpt_find_input_center_uia(hwnd) is not None
                except Exception:
                    continue
        except Exception:
            pass

    # Fallback for ChatGPT Desktop/Web shortcut.
    try:
        VK_CTRL, VK_SHIFT, VK_O, KEYUP = 0x11, 0x10, 0x4F, 0x0002
        user32.keybd_event(VK_CTRL, 0, 0, 0)
        user32.keybd_event(VK_SHIFT, 0, 0, 0)
        user32.keybd_event(VK_O, 0, 0, 0)
        time.sleep(0.08)
        user32.keybd_event(VK_O, 0, KEYUP, 0)
        user32.keybd_event(VK_SHIFT, 0, KEYUP, 0)
        user32.keybd_event(VK_CTRL, 0, KEYUP, 0)
        time.sleep(1.0)
        return _chatgpt_find_input_center_uia(hwnd) is not None or _chatgpt_find_input_center(hwnd) is not None
    except Exception:
        return False


def _chatgpt_foreground_control_available(hwnd: int) -> bool:
    """Return whether this process can actually drive ChatGPT with keyboard/mouse."""
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)
        time.sleep(0.1)
        if not user32.SetForegroundWindow(hwnd):
            return False
        time.sleep(0.2)
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _chatgpt_find_input_center(hwnd: int) -> Optional[tuple[int, int]]:
    """Locate ChatGPT's message box by scanning the window screenshot.

    ChatGPT's empty-new-chat input sits around the vertical centre, while an
    active conversation puts it near the bottom. Fixed coordinates break across
    these states, so detect the broad dark-grey input bar in the right pane.
    """
    uia_center = _chatgpt_find_input_center_uia(hwnd)
    if uia_center:
        return uia_center

    try:
        from PIL import ImageGrab

        rect = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        width, height = right - left, bottom - top
        if width <= 300 or height <= 300:
            return None

        img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).convert("RGB")
        x0 = max(int(width * 0.30), 360)
        x1 = max(x0 + 80, width - 45)
        y0 = 120
        y1 = max(y0 + 80, height - 60)

        best_y = -1
        best_count = 0
        for y in range(y0, y1):
            count = 0
            for x in range(x0, x1, 3):
                r, g, b = img.getpixel((x, y))
                if 24 <= r <= 70 and 24 <= g <= 70 and 24 <= b <= 70 and max(r, g, b) - min(r, g, b) <= 18:
                    count += 1
            if count > best_count:
                best_count = count
                best_y = y

        if best_y < 0 or best_count < max(40, int((x1 - x0) / 18)):
            return None

        runs: List[tuple[int, int]] = []
        run_start: Optional[int] = None
        for x in range(x0, x1):
            r, g, b = img.getpixel((x, best_y))
            is_bar = 24 <= r <= 70 and 24 <= g <= 70 and 24 <= b <= 70 and max(r, g, b) - min(r, g, b) <= 18
            if is_bar and run_start is None:
                run_start = x
            elif not is_bar and run_start is not None:
                if x - run_start >= 80:
                    runs.append((run_start, x - 1))
                run_start = None
        if run_start is not None and x1 - run_start >= 80:
            runs.append((run_start, x1 - 1))
        if not runs:
            return None

        run_left, run_right = max(runs, key=lambda item: item[1] - item[0])
        cx = left + (run_left + run_right) // 2
        cy = top + best_y
        return cx, cy
    except Exception:
        return None


def _chatgpt_focus_and_click_input(hwnd: int) -> bool:
    """Bring ChatGPT window to foreground and click the message input area.

    ChatGPT moves the input between centre (empty new chat) and bottom
    (existing conversation). Prefer screenshot detection; fall back to centre.
    """
    user32 = ctypes.windll.user32
    try:
        user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.4)
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        detected = _chatgpt_find_input_center(hwnd)
        if detected:
            cx, cy = detected
        else:
            cx = (rect.left + rect.right) // 2
            cy = rect.top + int((rect.bottom - rect.top) * 0.50)
        user32.SetCursorPos(int(cx), int(cy))
        MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.15)
        return True
    except Exception:
        return False


def _chatgpt_click_last_copy_button(hwnd: int) -> bool:
    """Click the copy icon under ChatGPT's last visible assistant response.

    ChatGPT Desktop's Electron UI does not expose useful UIA button metadata in
    current builds, and focus remains in the input after sending. Detect the
    bottom-most icon row in the main content pane and click its left-most icon,
    which is ChatGPT's copy response button.
    """
    try:
        from PIL import ImageGrab

        user32 = ctypes.windll.user32
        rect = ctypes.wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        width, height = right - left, bottom - top
        if width <= 300 or height <= 300:
            return False

        img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).convert("RGB")
        x0 = max(int(width * 0.30), 390)
        x1 = max(x0 + 80, width - 70)
        y0 = 140
        y1 = max(y0 + 80, height - 155)

        bright: set[tuple[int, int]] = set()
        for y in range(y0, y1):
            for x in range(x0, x1):
                r, g, b = img.getpixel((x, y))
                if r >= 175 and g >= 175 and b >= 175 and max(r, g, b) - min(r, g, b) <= 55:
                    bright.add((x, y))

        seen: set[tuple[int, int]] = set()
        components: List[tuple[int, int, int, int, int]] = []
        for point in list(bright):
            if point in seen:
                continue
            stack = [point]
            seen.add(point)
            xs: List[int] = []
            ys: List[int] = []
            count = 0
            while stack:
                x, y = stack.pop()
                xs.append(x)
                ys.append(y)
                count += 1
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    np = (nx, ny)
                    if np in bright and np not in seen:
                        seen.add(np)
                        stack.append(np)
            if count < 8:
                continue
            bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
            bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
            if 4 <= bw <= 42 and 4 <= bh <= 42:
                components.append((bx0, by0, bx1, by1, count))

        if not components:
            return False

        bottom_y = max((c[1] + c[3]) // 2 for c in components)
        row = [c for c in components if abs(((c[1] + c[3]) // 2) - bottom_y) <= 18]
        if not row:
            return False
        target = min(row, key=lambda c: c[0])
        cx = left + (target[0] + target[2]) // 2
        cy = top + (target[1] + target[3]) // 2

        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        user32.SetCursorPos(int(cx), int(cy))
        MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.5)
        return True
    except Exception:
        return False


def _chatgpt_extract_visible_response_text(hwnd: int, prompt: str) -> Optional[str]:
    """Extract the assistant response from ChatGPT's UIA text nodes.

    This is a fallback for current ChatGPT Desktop builds where the copy button
    can be visible but not reliably triggered by synthetic clicks.
    """
    if not _PW_OK:
        return None
    try:
        import pywinauto as _pw

        rect = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        width, height = right - left, bottom - top
        content_left = left + max(int(width * 0.30), 390)
        input_top = bottom - 130

        prompt_s = prompt.strip()
        response_parts: List[str] = []
        loose_candidates: List[tuple[int, int, str]] = []
        seen_prompt = False
        stop_texts = (
            "想問什麼都可以",
            "ChatGPT 可能會出錯",
            "聊天歷程紀錄",
        )

        app = _pw.Application(backend="uia").connect(handle=hwnd, timeout=5)
        win = app.window(handle=hwnd)
        for ctrl in win.descendants():
            try:
                if ctrl.element_info.control_type != "Text":
                    continue
                text = (ctrl.window_text() or "").strip()
                if not text or any(stop in text for stop in stop_texts):
                    continue
                r = ctrl.rectangle()
                if r.left < content_left or r.top < top + 40 or r.top > input_top:
                    continue

                is_prompt = (
                    text == prompt_s
                    or prompt_s in text
                    or text.startswith("URUK system context:")
                )
                if is_prompt:
                    seen_prompt = True
                    response_parts = []
                    continue

                if seen_prompt:
                    response_parts.append(text)
                else:
                    loose_candidates.append((r.top, r.left, text))
            except Exception:
                continue

        parts = response_parts

        deduped: List[str] = []
        for part in parts:
            if part and part not in deduped:
                deduped.append(part)
        result = "\n".join(deduped).strip()
        if result and result != prompt_s:
            return result
    except Exception:
        return None
    return None


def chatgpt_send_and_receive(prompt: str, timeout: float = 180.0, *, new_conversation: bool = False) -> dict:
    """Send a prompt to ChatGPT Desktop and return its response.

    Design principles (after previous debugging):
    - Find window by PID (not title): ChatGPT Desktop changes window title to the
      conversation name, so title-based search returns empty.
    - No pywinauto: its UIA connect() blocks the thread indefinitely on ChatGPT's
      React/Electron UI; ctypes-only path avoids all such hangs.
    - Flat wait instead of poll: ChatGPT's stop button has no accessible name, so
      _has_stop_button always returns False and the poll exits in 2.4s with junk.
    - Hard 90s cap: build_plan takes ~10s, so total relay fits in ~100s.
    """
    if sys.platform != "win32":
        return {"ok": False, "error": "ChatGPT Desktop relay is Windows-only."}
    if not _is_running(_KNOWN_APPS.get("chatgpt", {}).get("process_names", [])):
        return {"ok": False, "error": "chatgpt_desktop_not_running"}

    _hard_timeout = min(timeout, 90.0)
    _t0 = time.time()

    def _elapsed() -> float:
        return time.time() - _t0

    def _remaining() -> float:
        return max(0.0, _hard_timeout - _elapsed())

    # ── Step 1: Locate the main ChatGPT window by PID ────────────────────────
    hwnd = _find_chatgpt_hwnd()
    if not hwnd:
        return {"ok": False, "error": "chatgpt_window_not_found: no ChatGPT window ≥300×300px"}

    if not _chatgpt_foreground_control_available(hwnd):
        return {
            "ok": False,
            "error": "chatgpt_desktop_input_injection_unavailable: foreground window control denied",
            "elapsed_s": round(_elapsed(), 1),
            "hwnd": hwnd,
        }

    if new_conversation and not _chatgpt_start_new_conversation(hwnd):
        return {
            "ok": False,
            "error": "chatgpt_new_conversation_failed",
            "elapsed_s": round(_elapsed(), 1),
            "hwnd": hwnd,
        }

    # ── Step 2: Focus window + click input area ───────────────────────────────
    if not _chatgpt_focus_and_click_input(hwnd):
        return {
            "ok": False,
            "error": "chatgpt_focus_click_failed",
            "elapsed_s": round(_elapsed(), 1),
            "hwnd": hwnd,
        }

    # ── Step 3: Write prompt to clipboard, paste, press Enter ────────────────
    try:
        _set_clipboard(prompt)
        time.sleep(0.2)
    except Exception as e:
        return {"ok": False, "error": f"clipboard_set failed: {e}"}

    user32 = ctypes.windll.user32
    VK_CTRL, VK_V, VK_RETURN, KEYUP = 0x11, 0x56, 0x0D, 0x0002

    # Ctrl+V to paste
    user32.keybd_event(VK_CTRL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.08)
    user32.keybd_event(VK_V, 0, KEYUP, 0)
    user32.keybd_event(VK_CTRL, 0, KEYUP, 0)
    time.sleep(0.25)

    # Enter to submit
    user32.keybd_event(VK_RETURN, 0, 0, 0)
    time.sleep(0.07)
    user32.keybd_event(VK_RETURN, 0, KEYUP, 0)

    # ── Step 4: Wait for ChatGPT to respond (flat wait) ───────────────────────
    # ChatGPT Desktop typically responds in 10-30s for short prompts;
    # upgrade prompts (~7000 chars) may take 60s.  Use most of our budget.
    flat_wait = max(10.0, min(60.0, _remaining() - 8.0))
    time.sleep(flat_wait)

    # ── Step 5: Copy response — try multiple strategies ───────────────────────
    # Strategy A: click the last visible "Copy" button inside the ChatGPT window
    # (appears after each completed response).
    try:
        _set_clipboard("")
    except Exception:
        pass

    _copied = _chatgpt_click_last_copy_button(hwnd)
    if _PW_OK:
        try:
            import pywinauto as _pw
            _app = _pw.Application(backend="uia").connect(handle=hwnd, timeout=3)
            _win = _app.window(handle=hwnd)
            _btns = []
            for b in _win.descendants():
                name = b.window_text() or ""
                lname = name.lower()
                if b.element_info.control_type == "Button" and (
                    "copy" in lname or "複製回應" in name or "複製訊息" in name
                ):
                    _btns.append(b)
            if _btns:
                try:
                    _btns[-1].invoke()
                except Exception:
                    _btns[-1].click_input()
                time.sleep(0.5)
                _copied = True
        except Exception:
            pass

    # Strategy B: Ctrl+A then Ctrl+C (select all + copy)
    if not _copied:
        VK_A, VK_C = 0x41, 0x43
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        # Ctrl+A
        user32.keybd_event(VK_CTRL, 0, 0, 0)
        user32.keybd_event(VK_A, 0, 0, 0)
        time.sleep(0.06)
        user32.keybd_event(VK_A, 0, KEYUP, 0)
        user32.keybd_event(VK_CTRL, 0, KEYUP, 0)
        time.sleep(0.15)
        # Ctrl+C
        user32.keybd_event(VK_CTRL, 0, 0, 0)
        user32.keybd_event(VK_C, 0, 0, 0)
        time.sleep(0.06)
        user32.keybd_event(VK_C, 0, KEYUP, 0)
        user32.keybd_event(VK_CTRL, 0, KEYUP, 0)
        time.sleep(0.3)

    # ── Step 6: Read clipboard ────────────────────────────────────────────────
    clip = _read_clipboard_now()
    elapsed = _elapsed()
    if clip and clip.strip() and clip.strip() != prompt.strip():
        return {
            "ok": True,
            "response": clip,
            "method": "chatgpt_ctypes_clipboard",
            "elapsed_s": round(elapsed, 1),
            "hwnd": hwnd,
        }

    # Nothing useful in clipboard — hard fail
    extracted = _chatgpt_extract_visible_response_text(hwnd, prompt)
    if extracted:
        return {
            "ok": True,
            "response": extracted,
            "method": "chatgpt_uia_text",
            "elapsed_s": round(elapsed, 1),
            "hwnd": hwnd,
        }

    return {
        "ok": False,
        "error": f"chatgpt_no_response: clipboard empty after {elapsed:.0f}s",
        "elapsed_s": round(elapsed, 1),
        "hwnd": hwnd,
    }


async def _send_and_receive_inner(
    app_key: str,
    message: str,
    timeout: float = 90.0,
    relay_mode: Optional[str] = None,
    new_conversation: Optional[bool] = None,
) -> dict:
    """Send message to target app and wait for response."""
    cfg = _KNOWN_APPS.get(app_key, {})
    if cfg.get("alias"):
        app_key = cfg["alias"]
        cfg = _KNOWN_APPS.get(app_key, {})
    if not cfg:
        return {"ok": False, "error": f"Unknown app: {app_key}"}
    if sys.platform != "win32":
        return {"ok": False, "error": "App control is Windows-only."}

    # Claude Code: subprocess -p, no UI injection needed
    if app_key == "claude_code":
        from services.relay_protocol import format_relay_message
        formatted = format_relay_message("claude_code", message, relay_mode)
        return await asyncio.to_thread(_send_claude_code_subprocess, formatted, timeout)

    # ChatGPT Desktop
    if app_key == "chatgpt":
        from services.relay_protocol import format_chatgpt_relay_message
        formatted = format_chatgpt_relay_message(message, relay_mode=relay_mode)
        return await asyncio.to_thread(
            chatgpt_send_and_receive,
            formatted,
            timeout,
            new_conversation=bool(new_conversation),
        )

    # Codex Desktop
    if app_key == "codex":
        from services.relay_protocol import format_codex_relay_message
        formatted = format_codex_relay_message(message, relay_mode)
        cli_result = await asyncio.to_thread(_call_codex_cli, formatted, timeout)
        if cli_result.get("ok"):
            cli_result["new_conversation"] = True
            return cli_result
        cfg_c = _KNOWN_APPS.get("codex", cfg)
        if not _is_running(cfg_c["process_names"]):
            return cli_result if cli_result else {"ok": False, "error": "Codex is not running."}
        if new_conversation is None:
            new_conversation = True
        send_r = await send_to_app("codex", formatted, new_conversation=bool(new_conversation))
        if not send_r.get("ok"):
            return send_r
        read_r = await asyncio.to_thread(_poll_and_read, cfg_c, formatted, timeout)
        if read_r.get("ok"):
            read_r["cli_fallback_error"] = cli_result.get("error")
            return read_r
        fallback = await asyncio.to_thread(_clipboard_read_response, cfg_c, 15.0)
        if fallback:
            fallback["cli_fallback_error"] = cli_result.get("error")
        return fallback

    # Claude Desktop / cowork (ChatGPT handled above)
    if not _is_running(cfg["process_names"]):
        return {"ok": False, "error": f"{cfg.get('display', app_key)} is not running."}
    from services.relay_protocol import format_relay_message
    formatted = format_relay_message(app_key, message, relay_mode)
    if new_conversation is None:
        new_conversation = app_key in {"claude", "codex", "cowork"}
    send_r = await send_to_app(app_key, formatted, new_conversation=bool(new_conversation))
    if not send_r.get("ok"):
        return send_r
    read_r = await asyncio.to_thread(_poll_and_read, cfg, formatted, timeout)
    if read_r.get("ok"):
        read_r["send"] = send_r
        read_r["new_conversation"] = bool(new_conversation)
        return read_r
    return await asyncio.to_thread(_clipboard_read_response, cfg, 15.0)


async def send_and_receive(
    app_key: str,
    message: str,
    timeout: float = 90.0,
    relay_mode: Optional[str] = None,
    new_conversation: Optional[bool] = None,
) -> dict:
    """Tracked public wrapper for one desktop/CLI model relay request."""
    from services.inference_governor import execute_model_call

    return await execute_model_call(
        lambda: _send_and_receive_inner(
            app_key,
            message,
            timeout=timeout,
            relay_mode=relay_mode,
            new_conversation=new_conversation,
        ),
        role=relay_mode or "app_relay",
        provider=f"{app_key}_desktop",
        model=app_key,
    )
