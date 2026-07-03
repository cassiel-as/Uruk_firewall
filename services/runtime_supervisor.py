"""Runtime watchdog for a production-style URUK server process."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, TextIO

from services.runtime_dependencies import (
    build_ollama_command,
    build_shadow_command,
    runtime_dependency_status,
)


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = ROOT / "data" / "runtime"
LOG_DIR = ROOT / "logs" / "runtime"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def watchdog_state_path(port: int) -> Path:
    name = "watchdog_state.json" if int(port) == 8080 else f"watchdog_state_{int(port)}.json"
    return RUNTIME_DIR / name


def build_server_command(*, host: str, port: int, log_level: str = "warning") -> list[str]:
    return [
        sys.executable,
        "-X",
        "utf8",
        str(ROOT / "server_launcher.py"),
        "--host",
        str(host),
        "--port",
        str(int(port)),
        "--log-level",
        str(log_level),
    ]


def health_probe(base_url: str, timeout: float = 3.0) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/runtime/status",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
        identity = data.get("runtime_identity") or {}
        healthy = (
            response.status == 200
            and data.get("ok") is True
            and identity.get("id") == "uruk_protocol_carrier"
        )
        return {
            "healthy": healthy,
            "status_code": response.status,
            "runtime_pid": data.get("pid"),
            "run_id": data.get("run_id"),
            "identity_id": identity.get("id"),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "checked_at": _now(),
        }
    except Exception as exc:
        return {
            "healthy": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "checked_at": _now(),
        }


@dataclass
class SupervisorConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    interval_seconds: float = 5.0
    health_timeout_seconds: float = 3.0
    startup_grace_seconds: float = 20.0
    failure_threshold: int = 3
    max_restarts: int = 5
    restart_window_seconds: float = 900.0
    healthy_reset_seconds: float = 300.0
    companion_startup_grace_seconds: float = 30.0
    restart_backoff_seconds: float = 2.0
    run_seconds: float = 0.0
    log_level: str = "warning"
    manage_shadow: bool = False
    manage_ollama: bool = False

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{int(self.port)}"


class RuntimeSupervisor:
    def __init__(
        self,
        config: SupervisorConfig,
        *,
        state_path: Optional[Path] = None,
        log_dir: Optional[Path] = None,
    ) -> None:
        self.config = config
        self.state_path = Path(state_path or watchdog_state_path(config.port))
        self.log_dir = Path(log_dir or LOG_DIR)
        self.process: Optional[subprocess.Popen] = None
        self._stdout: Optional[TextIO] = None
        self._stderr: Optional[TextIO] = None
        self.started_at = _now()
        self.restart_count = 0
        self.restart_history: list[float] = []
        self.healthy_since_monotonic: Optional[float] = None
        self.consecutive_failures = 0
        self.last_health: Dict[str, Any] = {}
        self.dependencies: Dict[str, Any] = {}
        self.last_error = ""
        self.last_state_write_error = ""
        self.companions: Dict[str, subprocess.Popen] = {}
        self._companion_started_at: Dict[str, float] = {}
        self._companion_logs: Dict[str, tuple[TextIO, TextIO]] = {}

    def _write_state(self, status: str, **extra: Any) -> None:
        now_epoch = time.time()
        self._prune_restart_history(now_epoch)
        payload = {
            "schema_version": "uruk_runtime_watchdog.v2",
            "status": status,
            "started_at": self.started_at,
            "updated_at": _now(),
            "watchdog_pid": os.getpid(),
            "child_pid": self.process.pid if self.process and self.process.poll() is None else None,
            "restart_count": self.restart_count,
            "recent_restart_count": len(self.restart_history),
            "restart_window_seconds": self.config.restart_window_seconds,
            "restart_history": [
                datetime.fromtimestamp(item).isoformat(timespec="seconds")
                for item in self.restart_history
            ],
            "consecutive_failures": self.consecutive_failures,
            "last_health": self.last_health,
            "dependencies": self.dependencies,
            "companion_pids": {
                name: process.pid
                for name, process in self.companions.items()
                if process.poll() is None
            },
            "last_error": self.last_error,
            "last_state_write_error": self.last_state_write_error,
            "config": asdict(self.config),
            **extra,
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self.state_path)
            self.last_state_write_error = ""
        except Exception as exc:  # noqa: BLE001 - watchdog must keep supervising
            self.last_state_write_error = f"{type(exc).__name__}: {str(exc)[:240]}"

    def _read_state(self) -> Dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else {}
        except Exception:
            return {}

    def _prune_restart_history(self, now: Optional[float] = None) -> None:
        now = time.time() if now is None else float(now)
        window = max(1.0, float(self.config.restart_window_seconds))
        self.restart_history = [
            item for item in self.restart_history
            if now - item < window
        ]

    def _restart_budget_available(self, now: Optional[float] = None) -> bool:
        self._prune_restart_history(now)
        return len(self.restart_history) < max(0, int(self.config.max_restarts))

    def _note_healthy(self, now_monotonic: Optional[float] = None) -> None:
        now_monotonic = time.monotonic() if now_monotonic is None else float(now_monotonic)
        if self.healthy_since_monotonic is None:
            self.healthy_since_monotonic = now_monotonic
            return
        if now_monotonic - self.healthy_since_monotonic >= max(1.0, float(self.config.healthy_reset_seconds)):
            self.restart_history.clear()
            self.healthy_since_monotonic = now_monotonic

    def _note_unhealthy(self) -> None:
        self.healthy_since_monotonic = None

    def _dependency_degradation_reason(self) -> str:
        if not self.dependencies:
            return ""
        if not self.dependencies.get("healthy", False):
            return "required runtime dependency is unhealthy"
        if self.dependencies.get("secure") is False:
            return "runtime dependency security boundary is degraded"
        return ""

    def _open_logs(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = self.log_dir / f"server_{self.config.port}.stdout.log"
        stderr_path = self.log_dir / f"server_{self.config.port}.stderr.log"
        self._stdout = stdout_path.open("a", encoding="utf-8")
        self._stderr = stderr_path.open("a", encoding="utf-8")

    def _close_logs(self) -> None:
        for handle in (self._stdout, self._stderr):
            if handle:
                handle.close()
        self._stdout = None
        self._stderr = None

    def _start_companion(self, name: str, command: list[str] | None) -> bool:
        if not command:
            return False
        existing = self.companions.get(name)
        if existing and existing.poll() is None:
            age = time.monotonic() - self._companion_started_at.get(name, 0.0)
            if age < max(1.0, float(self.config.companion_startup_grace_seconds)):
                return True
            # Called only when the dependency endpoint is unhealthy. A live
            # wrapper with a dead child must be rebuilt after startup grace.
            self._stop_companion(name)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stdout = (self.log_dir / f"{name}.stdout.log").open("a", encoding="utf-8")
        stderr = (self.log_dir / f"{name}.stderr.log").open("a", encoding="utf-8")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            environment = os.environ.copy()
            if name == "ollama":
                environment["OLLAMA_HOST"] = "127.0.0.1:11434"
            self.companions[name] = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=stdout,
                stderr=stderr,
                text=True,
                creationflags=creationflags,
                env=environment,
            )
            self._companion_logs[name] = (stdout, stderr)
            self._companion_started_at[name] = time.monotonic()
            return True
        except Exception:
            stdout.close()
            stderr.close()
            return False

    def _stop_companion(self, name: str) -> None:
        process = self.companions.pop(name, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        handles = self._companion_logs.pop(name, None)
        if handles:
            for handle in handles:
                handle.close()
        self._companion_started_at.pop(name, None)

    def ensure_companions(self) -> Dict[str, Any]:
        self.dependencies = runtime_dependency_status(ROOT, timeout=self.config.health_timeout_seconds)
        items = self.dependencies.get("dependencies") or {}
        if self.config.manage_shadow and not (items.get("controller_shadow") or {}).get("healthy"):
            self._start_companion("controller_shadow", build_shadow_command(ROOT))
        if self.config.manage_ollama and not (items.get("ollama") or {}).get("healthy"):
            self._start_companion("ollama", build_ollama_command())
        return self.dependencies

    def stop_companions(self) -> None:
        for name in list(self.companions):
            self._stop_companion(name)

    def spawn(self) -> None:
        self.ensure_companions()
        self._close_logs()
        self._open_logs()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self.process = subprocess.Popen(
            build_server_command(
                host=self.config.host,
                port=self.config.port,
                log_level=self.config.log_level,
            ),
            cwd=ROOT,
            stdout=self._stdout,
            stderr=self._stderr,
            text=True,
            creationflags=creationflags,
        )
        self.consecutive_failures = 0
        self.last_error = ""
        self._write_state("starting")

    def stop_child(self) -> None:
        process = self.process
        if not process or process.poll() is not None:
            self._close_logs()
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        self._close_logs()

    def _restart(self, reason: str) -> bool:
        self.last_error = reason
        self._note_unhealthy()
        self.stop_child()
        now = time.time()
        if not self._restart_budget_available(now):
            self._write_state("failed", reason=reason)
            return False
        self.restart_count += 1
        self.restart_history.append(now)
        self._write_state("restarting", reason=reason)
        time.sleep(max(0.0, float(self.config.restart_backoff_seconds)))
        self.spawn()
        return True

    def run(self) -> int:
        existing = health_probe(self.config.base_url, timeout=self.config.health_timeout_seconds)
        if existing.get("healthy"):
            self.last_health = existing
            self.last_error = "Healthy URUK server already occupies the target port; watchdog did not take ownership."
            self._write_state("existing_server", reason=self.last_error)
            return 2

        started_clock = time.monotonic()
        child_started_clock = started_clock
        self.spawn()
        try:
            while True:
                now = time.monotonic()
                if self.config.run_seconds > 0 and now - started_clock >= self.config.run_seconds:
                    self._write_state("completed")
                    return 0

                if self.process and self.process.poll() is not None:
                    code = self.process.returncode
                    if not self._restart(f"child exited with code {code}"):
                        return 1
                    child_started_clock = time.monotonic()
                    continue

                self.last_health = health_probe(
                    self.config.base_url,
                    timeout=self.config.health_timeout_seconds,
                )
                self.ensure_companions()
                if self.last_health.get("healthy"):
                    self.consecutive_failures = 0
                    dependency_reason = self._dependency_degradation_reason()
                    if dependency_reason:
                        self._note_unhealthy()
                        self.last_error = dependency_reason
                        self._write_state("degraded_dependencies", reason=dependency_reason)
                    else:
                        self._note_healthy(now)
                        self.last_error = ""
                        self._write_state("healthy")
                elif now - child_started_clock < max(0.0, self.config.startup_grace_seconds):
                    self._note_unhealthy()
                    self._write_state("starting")
                else:
                    self._note_unhealthy()
                    self.consecutive_failures += 1
                    self.last_error = str(self.last_health.get("error") or "health probe failed")
                    self._write_state("degraded")
                    if self.consecutive_failures >= max(1, int(self.config.failure_threshold)):
                        if not self._restart(self.last_error):
                            return 1
                        child_started_clock = time.monotonic()
                time.sleep(max(0.1, float(self.config.interval_seconds)))
        except KeyboardInterrupt:
            self._write_state("stopping")
            return 0
        finally:
            self.stop_child()
            self.stop_companions()
            final = self._read_state()
            final_status = str(final.get("status") or "")
            if final_status in {"failed", "existing_server", "completed"}:
                extra = {"reason": final["reason"]} if final.get("reason") else {}
                self._write_state(final_status, **extra)
            else:
                self._write_state("stopped")
