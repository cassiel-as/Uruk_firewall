"""Desktop launcher for URUK Trinity Console.

When pywebview is available, URUK opens in a native window. Otherwise it
falls back to the system browser while keeping the production server running.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
os.chdir(APP_ROOT)
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from server_launcher import run_server  # noqa: E402


def find_free_port(preferred: int = 8765) -> int:
    for port in range(int(preferred), int(preferred) + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free local port found from {preferred} to {preferred + 19}.")


def _validate_config() -> bool:
    cfg_path = APP_ROOT / "config" / "nodes.yaml"
    if cfg_path.exists():
        return True
    print("Missing config/nodes.yaml.", file=sys.stderr)
    print(f'Create it from: "{APP_ROOT}\\config\\nodes.example.yaml"', file=sys.stderr)
    return False


def _open_browser_later(url: str, delay: float = 1.5) -> None:
    time.sleep(delay)
    webbrowser.open(url)


def main() -> int:
    parser = argparse.ArgumentParser(description="Open URUK in a native window or browser fallback.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("URUK_DESKTOP_PORT", "8765")))
    parser.add_argument("--browser-only", action="store_true", help="Skip pywebview and open the system browser.")
    args = parser.parse_args()

    if not _validate_config():
        return 1

    port = find_free_port(args.port)
    url = f"http://127.0.0.1:{port}"
    webview = None
    if not args.browser_only:
        try:
            import webview as imported_webview

            webview = imported_webview
        except ImportError:
            print("pywebview is unavailable; falling back to the system browser.")

    if webview is None:
        threading.Thread(target=_open_browser_later, args=(url,), daemon=True).start()
        print(f"URUK Desktop browser fallback: {url}")
        return run_server(host="127.0.0.1", port=port, log_level="warning", access_log=False)

    server_thread = threading.Thread(
        target=run_server,
        kwargs={
            "host": "127.0.0.1",
            "port": port,
            "log_level": "warning",
            "access_log": False,
        },
        daemon=True,
    )
    server_thread.start()
    time.sleep(1.5)
    print(f"URUK Trinity Console Desktop: {url}")
    webview.create_window(
        "URUK Trinity Console",
        url,
        width=1400,
        height=900,
        min_size=(900, 600),
        text_select=True,
    )
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
