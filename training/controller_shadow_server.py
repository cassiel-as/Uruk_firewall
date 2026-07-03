"""Loopback-only HTTP server for the trained URUK controller shadow."""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.peft_controller_runtime import PeftControllerRuntime  # noqa: E402


class ControllerHandler(BaseHTTPRequestHandler):
    runtime: PeftControllerRuntime
    server_version = "URUKControllerShadow/1.0"

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._json(404, {"ok": False, "error": "not found"})
            return
        self._json(200, {
            "ok": True,
            "model": self.runtime.base_model,
            "adapter": self.runtime.adapter,
            "authority": "shadow_only",
        })

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/predict":
            self._json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 65536:
                raise ValueError("request body must be between 1 and 65536 bytes")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            model_input = payload.get("input")
            if not isinstance(model_input, dict):
                raise ValueError("input must be an object")
            started = time.perf_counter()
            decision = self.runtime.predict(model_input)
            self._json(200, {
                "ok": True,
                "decision": decision,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "authority": "shadow_only",
            })
        except Exception as exc:
            self._json(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the trained URUK controller in shadow-only mode.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--adapter",
        default=str(ROOT / "training" / "artifacts" / "uruk-controller-qwen3-1.7b-lora-v3-1"),
    )
    parser.add_argument("--base-model", default="Qwen/Qwen3-1.7B")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Shadow controller must bind to loopback only.")

    ControllerHandler.runtime = PeftControllerRuntime(adapter=Path(args.adapter), base_model=args.base_model)
    server = ThreadingHTTPServer((args.host, args.port), ControllerHandler)
    print(f"URUK controller shadow listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
