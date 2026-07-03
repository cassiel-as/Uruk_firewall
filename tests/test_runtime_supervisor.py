import json
import threading
import tempfile
import time
from unittest.mock import MagicMock, patch
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from services.runtime_supervisor import (
    RuntimeSupervisor,
    SupervisorConfig,
    build_server_command,
    health_probe,
)
from services.runtime_dependencies import (
    _is_local_only_bind,
    build_ollama_command,
    build_shadow_command,
    controller_shadow_status,
)


class _RuntimeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/api/runtime/status":
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps({
            "ok": True,
            "pid": 1234,
            "run_id": "unit",
            "runtime_identity": {"id": "uruk_protocol_carrier"},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


def test_build_server_command_uses_production_launcher_without_reload():
    command = build_server_command(host="127.0.0.1", port=8765, log_level="warning")

    assert any(str(item).endswith("server_launcher.py") for item in command)
    assert "--port" in command
    assert "8765" in command
    assert "--reload" not in command


def test_health_probe_accepts_uruk_runtime_identity():
    server = HTTPServer(("127.0.0.1", 0), _RuntimeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = health_probe(f"http://127.0.0.1:{server.server_port}", timeout=2.0)
    finally:
        server.shutdown()
        server.server_close()

    assert result["healthy"] is True
    assert result["identity_id"] == "uruk_protocol_carrier"
    assert result["runtime_pid"] == 1234


def test_supervisor_writes_machine_readable_state(tmp_path):
    state_path = Path(tmp_path) / "watchdog.json"
    supervisor = RuntimeSupervisor(
        SupervisorConfig(port=8765, run_seconds=1),
        state_path=state_path,
        log_dir=Path(tmp_path) / "logs",
    )

    supervisor._write_state("starting")
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "uruk_runtime_watchdog.v2"
    assert payload["status"] == "starting"
    assert payload["config"]["port"] == 8765
    assert payload["config"]["manage_shadow"] is False
    assert payload["config"]["manage_ollama"] is False
    assert payload["recent_restart_count"] == 0
    assert not state_path.with_suffix(".json.tmp").exists()


def test_dependency_commands_are_bounded_and_explicit():
    shadow = build_shadow_command()
    ollama = build_ollama_command("ollama")

    assert shadow is not None
    assert shadow[-1].endswith("controller_shadow_server.py")
    assert ollama == ["ollama", "serve"]


def test_disabled_shadow_is_healthy_and_not_required():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config").mkdir()
        (root / "config" / "controller_shadow.json").write_text(
            json.dumps({"enabled": False}),
            encoding="utf-8",
        )
        status = controller_shadow_status(root)

    assert status["status"] == "disabled"
    assert status["healthy"] is True
    assert status["required"] is False


def test_local_only_bind_detection_rejects_wildcard_addresses():
    assert _is_local_only_bind(["127.0.0.1"]) is True
    assert _is_local_only_bind(["127.0.0.1", "::1"]) is True
    assert _is_local_only_bind(["0.0.0.0"]) is False
    assert _is_local_only_bind(["::"]) is False
    assert _is_local_only_bind([]) is None


def test_restart_budget_uses_sliding_window_instead_of_lifetime_count(tmp_path):
    supervisor = RuntimeSupervisor(
        SupervisorConfig(max_restarts=2, restart_window_seconds=60),
        state_path=Path(tmp_path) / "watchdog.json",
        log_dir=Path(tmp_path) / "logs",
    )
    now = time.time()
    supervisor.restart_count = 99
    supervisor.restart_history = [now - 120, now - 10]

    assert supervisor._restart_budget_available(now) is True
    assert len(supervisor.restart_history) == 1


def test_restart_budget_blocks_only_recent_restart_burst(tmp_path):
    supervisor = RuntimeSupervisor(
        SupervisorConfig(max_restarts=2, restart_window_seconds=60),
        state_path=Path(tmp_path) / "watchdog.json",
        log_dir=Path(tmp_path) / "logs",
    )
    now = time.time()
    supervisor.restart_history = [now - 20, now - 10]

    assert supervisor._restart_budget_available(now) is False


def test_sustained_health_restores_restart_budget(tmp_path):
    supervisor = RuntimeSupervisor(
        SupervisorConfig(max_restarts=2, healthy_reset_seconds=30),
        state_path=Path(tmp_path) / "watchdog.json",
        log_dir=Path(tmp_path) / "logs",
    )
    supervisor.restart_history = [time.time()]
    supervisor._note_healthy(now_monotonic=100)
    supervisor._note_healthy(now_monotonic=131)

    assert supervisor.restart_history == []


def test_dependency_security_degradation_is_reported(tmp_path):
    supervisor = RuntimeSupervisor(
        SupervisorConfig(),
        state_path=Path(tmp_path) / "watchdog.json",
        log_dir=Path(tmp_path) / "logs",
    )
    supervisor.dependencies = {"healthy": True, "secure": False}

    assert "security boundary" in supervisor._dependency_degradation_reason()


def test_stale_live_companion_wrapper_is_rebuilt(tmp_path):
    supervisor = RuntimeSupervisor(
        SupervisorConfig(companion_startup_grace_seconds=10),
        state_path=Path(tmp_path) / "watchdog.json",
        log_dir=Path(tmp_path) / "logs",
    )
    stale = MagicMock()
    stale.poll.return_value = None
    supervisor.companions["controller_shadow"] = stale
    supervisor._companion_started_at["controller_shadow"] = 1.0
    replacement = MagicMock()
    replacement.pid = 1234

    with patch("services.runtime_supervisor.time.monotonic", return_value=20.0), patch(
        "services.runtime_supervisor.subprocess.Popen", return_value=replacement
    ):
        started = supervisor._start_companion("controller_shadow", ["python", "shadow.py"])

    assert started is True
    stale.terminate.assert_called_once()
    assert supervisor.companions["controller_shadow"] is replacement
