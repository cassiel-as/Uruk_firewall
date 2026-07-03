import unittest

from services import app_controller


class _FakeInput:
    def click_input(self):
        return None


class _FakeWindow:
    def restore(self):
        return None

    def set_focus(self):
        return None

    def child_window(self, **kwargs):
        return _FakeInput()


class _FakePwApp:
    def __init__(self, *args, **kwargs):
        pass

    def connect(self, **kwargs):
        return self

    def window(self, **kwargs):
        return _FakeWindow()


class AppControllerTests(unittest.TestCase):
    def test_copilot_known_app_profile_is_registered(self):
        cfg = app_controller._KNOWN_APPS["copilot"]

        self.assertEqual(cfg["display"], "Windows Copilot")
        self.assertEqual(cfg["window_title"], "Copilot")
        self.assertIn("mscopilot.exe", cfg["process_names"])
        self.assertEqual(cfg["app_id"], "Microsoft.Copilot_8wekyb3d8bbwe!App")
        self.assertIn("file_search", cfg["capabilities"])

    def test_launch_app_uses_start_app_id_fallback(self):
        original_known_apps = dict(app_controller._KNOWN_APPS)
        original_is_running = app_controller._is_running
        original_popen = app_controller.subprocess.Popen
        calls = []

        class _FakePopen:
            def __init__(self, args, shell=False):
                calls.append({"args": args, "shell": shell})

        try:
            app_controller._KNOWN_APPS["unit_start_app"] = {
                "display": "Unit Start App",
                "icon": "UA",
                "process_names": ["unit-start-app.exe"],
                "window_title": "Unit Start App",
                "app_id": "Unit.App_123!App",
                "exe_candidates": [],
            }
            app_controller._is_running = lambda _names: False
            app_controller.subprocess.Popen = _FakePopen

            result = app_controller.launch_app("unit_start_app")
        finally:
            app_controller._KNOWN_APPS.clear()
            app_controller._KNOWN_APPS.update(original_known_apps)
            app_controller._is_running = original_is_running
            app_controller.subprocess.Popen = original_popen

        self.assertTrue(result["ok"], result)
        self.assertEqual(calls, [{
            "args": ["explorer.exe", "shell:appsFolder\\Unit.App_123!App"],
            "shell": False,
        }])

    def test_pywinauto_send_uses_clipboard_for_brace_heavy_prompt(self):
        original_pw_app = app_controller._PWApp
        original_send_keys = app_controller._pw_send_keys
        original_set_clipboard = app_controller._set_clipboard
        original_sleep = app_controller.time.sleep
        calls = []
        clipboard = []

        def fake_send_keys(value, *args, **kwargs):
            calls.append((value, args, kwargs))

        def fake_set_clipboard(value):
            clipboard.append(value)

        try:
            app_controller._PWApp = _FakePwApp
            app_controller._pw_send_keys = fake_send_keys
            app_controller._set_clipboard = fake_set_clipboard
            app_controller.time.sleep = lambda *_args, **_kwargs: None

            message = '[TOOL_SPEC:upgrade-unit]\npython_code: |\n  return {"ok": true}\n---'
            result = app_controller._send_pywinauto({"window_title": "ChatGPT"}, message)
        finally:
            app_controller._PWApp = original_pw_app
            app_controller._pw_send_keys = original_send_keys
            app_controller._set_clipboard = original_set_clipboard
            app_controller.time.sleep = original_sleep

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["method"], "pywinauto_clipboard")
        self.assertEqual(clipboard, [message])
        self.assertEqual([call[0] for call in calls], ["^v", "{ENTER}"])
        self.assertNotIn(message, [call[0] for call in calls])

    def test_chatgpt_send_returns_focus_error_when_click_fails(self):
        original_platform = app_controller.sys.platform
        original_is_running = app_controller._is_running
        original_find_hwnd = app_controller._find_chatgpt_hwnd
        original_foreground = app_controller._chatgpt_foreground_control_available
        original_focus_click = app_controller._chatgpt_focus_and_click_input
        try:
            app_controller.sys.platform = "win32"
            app_controller._is_running = lambda _names: True
            app_controller._find_chatgpt_hwnd = lambda: 12345
            app_controller._chatgpt_foreground_control_available = lambda _hwnd: True
            app_controller._chatgpt_focus_and_click_input = lambda _hwnd: False

            result = app_controller.chatgpt_send_and_receive('return {"ok": true}', timeout=1)
        finally:
            app_controller.sys.platform = original_platform
            app_controller._is_running = original_is_running
            app_controller._find_chatgpt_hwnd = original_find_hwnd
            app_controller._chatgpt_foreground_control_available = original_foreground
            app_controller._chatgpt_focus_and_click_input = original_focus_click

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"], "chatgpt_focus_click_failed")
        self.assertEqual(result["hwnd"], 12345)

    def test_chatgpt_send_fails_fast_when_foreground_control_unavailable(self):
        original_platform = app_controller.sys.platform
        original_is_running = app_controller._is_running
        original_find_hwnd = app_controller._find_chatgpt_hwnd
        original_foreground = app_controller._chatgpt_foreground_control_available
        try:
            app_controller.sys.platform = "win32"
            app_controller._is_running = lambda _names: True
            app_controller._find_chatgpt_hwnd = lambda: 12345
            app_controller._chatgpt_foreground_control_available = lambda _hwnd: False

            result = app_controller.chatgpt_send_and_receive("hello", timeout=60)
        finally:
            app_controller.sys.platform = original_platform
            app_controller._is_running = original_is_running
            app_controller._find_chatgpt_hwnd = original_find_hwnd
            app_controller._chatgpt_foreground_control_available = original_foreground

        self.assertFalse(result["ok"], result)
        self.assertIn("chatgpt_desktop_input_injection_unavailable", result["error"])
        self.assertLess(result["elapsed_s"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
