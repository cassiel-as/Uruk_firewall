"""CLI watchdog for the URUK production server launcher."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.runtime_supervisor import RuntimeSupervisor, SupervisorConfig  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Supervise URUK server health and restart on failure.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--interval", type=float, default=5.0, help="Health probe interval in seconds.")
    parser.add_argument("--health-timeout", type=float, default=3.0)
    parser.add_argument("--startup-grace", type=float, default=20.0)
    parser.add_argument("--failure-threshold", type=int, default=3)
    parser.add_argument("--max-restarts", type=int, default=5)
    parser.add_argument("--restart-window", type=float, default=900.0, help="Sliding restart budget window in seconds.")
    parser.add_argument("--healthy-reset", type=float, default=300.0, help="Healthy duration that restores restart budget.")
    parser.add_argument("--companion-startup-grace", type=float, default=30.0, help="Grace period before rebuilding an unhealthy live companion wrapper.")
    parser.add_argument("--restart-backoff", type=float, default=2.0)
    parser.add_argument("--run-seconds", type=float, default=0.0, help="Stop after N seconds; 0 runs forever.")
    parser.add_argument("--log-level", default="warning")
    parser.add_argument("--with-shadow", action="store_true", help="Start and monitor the configured controller shadow.")
    parser.add_argument("--with-ollama", action="store_true", help="Start and monitor local Ollama.")
    parser.add_argument("--state-path", default="", help="Optional watchdog state JSON path.")
    parser.add_argument("--log-dir", default="", help="Optional child server log directory.")
    args = parser.parse_args()

    config = SupervisorConfig(
        host=args.host,
        port=args.port,
        interval_seconds=max(0.1, args.interval),
        health_timeout_seconds=max(0.1, args.health_timeout),
        startup_grace_seconds=max(0.0, args.startup_grace),
        failure_threshold=max(1, args.failure_threshold),
        max_restarts=max(0, args.max_restarts),
        restart_window_seconds=max(1.0, args.restart_window),
        healthy_reset_seconds=max(1.0, args.healthy_reset),
        companion_startup_grace_seconds=max(1.0, args.companion_startup_grace),
        restart_backoff_seconds=max(0.0, args.restart_backoff),
        run_seconds=max(0.0, args.run_seconds),
        log_level=args.log_level,
        manage_shadow=bool(args.with_shadow),
        manage_ollama=bool(args.with_ollama),
    )
    supervisor = RuntimeSupervisor(
        config,
        state_path=Path(args.state_path) if args.state_path else None,
        log_dir=Path(args.log_dir) if args.log_dir else None,
    )
    code = supervisor.run()
    print(f"URUK watchdog finished with code={code}; state={supervisor.state_path}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
