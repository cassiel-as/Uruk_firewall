"""
URUK auto-upgraded tool: wait_for_window
Installed: 2026-05-30T14:14:31.949406
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='wait_for_window',
    description='Wait until a visible desktop window with a matching title appears, then return matched status, window title, hwnd, all matches, and elapsed time.',
    args=[ArgSpec(**a) for a in [{'name': 'title', 'type': 'str', 'required': True, 'description': 'Window title text to match.'}, {'name': 'timeout', 'type': 'float', 'required': False, 'description': 'Maximum seconds to wait; default 10, capped at 300.'}, {'name': 'poll_interval', 'type': 'float', 'required': False, 'description': 'Seconds between scans; default 0.25.'}, {'name': 'exact', 'type': 'bool', 'required': False, 'description': 'If true, require exact title match; otherwise substring match.'}, {'name': 'case_sensitive', 'type': 'bool', 'required': False, 'description': 'If true, match title using case-sensitive comparison.'}, {'name': 'visible_only', 'type': 'bool', 'required': False, 'description': 'If true, ignore hidden windows.'}]],
    needs_visual=False,
    category='nav',
)

def execute(args: dict) -> dict:
    try:
        import ctypes
        import time
        from ctypes import wintypes

        def as_bool(value, default=False):
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "y", "on")
            return bool(value)

        title = str(args.get("title", "")).strip()
        if not title:
            return {"error": "title is required"}

        timeout = float(args.get("timeout", 10.0))
        poll_interval = float(args.get("poll_interval", 0.25))
        timeout = max(0.0, min(timeout, 300.0))
        poll_interval = max(0.05, min(poll_interval, 5.0))
        exact = as_bool(args.get("exact"), False)
        case_sensitive = as_bool(args.get("case_sensitive"), False)
        visible_only = as_bool(args.get("visible_only"), True)

        user32 = ctypes.windll.user32
        target = title if case_sensitive else title.lower()

        def hwnd_to_int(hwnd):
            try:
                return int(hwnd)
            except Exception:
                return int(getattr(hwnd, "value", 0) or 0)

        def scan_windows():
            matches = []

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def enum_proc(hwnd, lparam):
                if visible_only and not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                window_title = buffer.value
                candidate = window_title if case_sensitive else window_title.lower()
                matched = candidate == target if exact else target in candidate
                if matched:
                    matches.append({"hwnd": hwnd_to_int(hwnd), "title": window_title})
                return True

            user32.EnumWindows(enum_proc, 0)
            return matches

        start = time.time()
        deadline = start + timeout
        while True:
            matches = scan_windows()
            elapsed = round(time.time() - start, 3)
            if matches:
                return {
                    "matched": True,
                    "timed_out": False,
                    "window": matches[0],
                    "matches": matches,
                    "elapsed_seconds": elapsed
                }
            if time.time() >= deadline:
                return {
                    "matched": False,
                    "timed_out": True,
                    "window": None,
                    "matches": [],
                    "elapsed_seconds": elapsed
                }
            time.sleep(poll_interval)
    except Exception as e:
        return {"error": str(e)}
