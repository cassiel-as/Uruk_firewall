"""Production-style launcher for URUK Trinity Console.

Unlike ``py app.py``, this entrypoint does not enable Uvicorn hot reload.
It is suitable for watchdog supervision and longer-running local use.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


APP_ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = APP_ROOT / "data" / "runtime"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def server_state_path(port: int) -> Path:
    name = "server_state.json" if int(port) == 8080 else f"server_state_{int(port)}.json"
    return RUNTIME_DIR / name


def write_server_state(port: int, status: str, **extra: Any) -> Path:
    path = server_state_path(port)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "schema_version": "uruk_server_state.v1",
        "status": status,
        "updated_at": _now(),
        "pid": os.getpid(),
        "host": extra.pop("host", os.environ.get("URUK_HOST", "127.0.0.1")),
        "port": int(port),
        "entrypoint": str(Path(__file__).resolve()),
        **extra,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _port_available(host: str, port: int) -> bool:
    bind_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((bind_host, int(port)))
            return True
        except OSError:
            return False


def _existing_uruk(base_url: str, timeout: float = 2.0) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/runtime/status",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
        identity = data.get("runtime_identity") or {}
        return {
            "healthy": response.status == 200
            and data.get("ok") is True
            and identity.get("id") == "uruk_protocol_carrier",
            "payload": data,
        }
    except Exception as exc:
        return {"healthy": False, "error": f"{type(exc).__name__}: {exc}"}


def run_server(*, host: str, port: int, log_level: str = "info", access_log: bool = True) -> int:
    import uvicorn

    os.chdir(APP_ROOT)
    os.environ["URUK_HOST"] = host
    os.environ["URUK_PORT"] = str(port)
    base_url = f"http://127.0.0.1:{port}"

    if not _port_available(host, port):
        existing = _existing_uruk(base_url)
        if existing.get("healthy"):
            write_server_state(port, "already_running", host=host, base_url=base_url)
            print(f"URUK server already running at {base_url}")
            return 0
        write_server_state(
            port,
            "bind_failed",
            host=host,
            base_url=base_url,
            error=f"Port {port} is already in use by another process.",
        )
        print(f"URUK production launcher: port {port} is already in use.", file=sys.stderr)
        return 1

    started_at = _now()
    write_server_state(port, "starting", host=host, base_url=base_url, started_at=started_at)
    print(f"URUK production server: {base_url}")
    try:
        uvicorn.run(
            "app:app",
            host=host,
            port=int(port),
            reload=False,
            workers=1,
            log_level=log_level,
            access_log=access_log,
        )
    except KeyboardInterrupt:
        write_server_state(port, "stopped", host=host, base_url=base_url, started_at=started_at)
        return 0
    except Exception as exc:
        write_server_state(
            port,
            "crashed",
            host=host,
            base_url=base_url,
            started_at=started_at,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    write_server_state(port, "stopped", host=host, base_url=base_url, started_at=started_at)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run URUK without development hot reload.")
    parser.add_argument("--host", default=os.environ.get("URUK_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("URUK_PORT", "8080")))
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--no-access-log", action="store_true")
    args = parser.parse_args()
    return run_server(
        host=str(args.host),
        port=int(args.port),
        log_level=str(args.log_level),
        access_log=not args.no_access_log,
    )


if __name__ == "__main__":
    raise SystemExit(main())
