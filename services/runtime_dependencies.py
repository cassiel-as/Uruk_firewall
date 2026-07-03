"""Health probes and launch commands for optional URUK runtime dependencies."""
from __future__ import annotations

import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
_LOOPBACK_ADDRESSES = {"127.0.0.1", "::1"}


def _probe_json(url: str, *, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return {
            "healthy": response.status == 200,
            "status_code": response.status,
            "payload": payload,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    except Exception as exc:
        return {
            "healthy": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }


def _listener_addresses(port: int) -> list[str]:
    """Return real TCP listener addresses when psutil can inspect them."""
    try:
        import psutil

        addresses = {
            str(conn.laddr.ip)
            for conn in psutil.net_connections(kind="tcp")
            if conn.status == psutil.CONN_LISTEN
            and conn.laddr
            and int(conn.laddr.port) == int(port)
        }
        return sorted(addresses)
    except Exception:
        return []


def _is_local_only_bind(addresses: list[str]) -> bool | None:
    if not addresses:
        return None
    return all(address in _LOOPBACK_ADDRESSES for address in addresses)


def controller_shadow_status(root: Path = ROOT, *, timeout: float = 0.5) -> dict[str, Any]:
    config_path = Path(root) / "config" / "controller_shadow.json"
    config: dict[str, Any] = {}
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    enabled = bool(config.get("enabled"))
    base_url = str(config.get("url") or "http://127.0.0.1:8766").rstrip("/")
    if not enabled:
        return {
            "name": "controller_shadow",
            "required": False,
            "configured": False,
            "healthy": True,
            "status": "disabled",
            "url": base_url,
        }
    result = _probe_json(f"{base_url}/health", timeout=timeout)
    payload = result.pop("payload", {}) if isinstance(result.get("payload"), dict) else {}
    healthy = bool(result.get("healthy")) and payload.get("authority") == "shadow_only"
    return {
        "name": "controller_shadow",
        "required": True,
        "configured": True,
        "healthy": healthy,
        "status": "healthy" if healthy else "offline",
        "url": base_url,
        "adapter": payload.get("adapter"),
        "authority": payload.get("authority"),
        **result,
        "healthy": healthy,
    }


def ollama_status(*, timeout: float = 0.5, base_url: str = "http://127.0.0.1:11434") -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    result = _probe_json(f"{base_url}/api/tags", timeout=timeout)
    payload = result.pop("payload", {}) if isinstance(result.get("payload"), dict) else {}
    listener_addresses = _listener_addresses(11434)
    local_only = _is_local_only_bind(listener_addresses)
    models = [
        str(item.get("name") or "")
        for item in (payload.get("models") or [])
        if isinstance(item, dict) and item.get("name")
    ]
    return {
        "name": "ollama",
        "required": True,
        "configured": True,
        "status": "healthy" if result.get("healthy") else "offline",
        "url": base_url,
        "model_count": len(models),
        "models": models,
        "listener_addresses": listener_addresses,
        "local_only": local_only,
        "security_status": (
            "local_only" if local_only is True
            else "network_exposed" if local_only is False
            else "listener_unknown"
        ),
        **result,
    }


def runtime_dependency_status(root: Path = ROOT, *, timeout: float = 0.5) -> dict[str, Any]:
    dependencies = {
        "controller_shadow": controller_shadow_status(root, timeout=timeout),
        "ollama": ollama_status(timeout=timeout),
    }
    required = [item for item in dependencies.values() if item.get("required")]
    return {
        "schema_version": "uruk_runtime_dependencies.v1",
        "healthy": all(bool(item.get("healthy")) for item in required),
        "secure": all(item.get("local_only", True) is not False for item in required),
        "required_count": len(required),
        "healthy_required_count": sum(bool(item.get("healthy")) for item in required),
        "dependencies": dependencies,
    }


def build_shadow_command(root: Path = ROOT) -> list[str] | None:
    root = Path(root)
    python = root / ".venv-training" / "Scripts" / "python.exe"
    server = root / "training" / "controller_shadow_server.py"
    if not python.exists() or not server.exists():
        return None
    return [str(python), "-X", "utf8", str(server)]


def build_ollama_command(executable: str | None = None) -> list[str] | None:
    command = executable or shutil.which("ollama")
    return [str(command), "serve"] if command else None
