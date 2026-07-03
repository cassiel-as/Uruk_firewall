"""
Stress test CLI for URUK Trinity Console failover engine.

Two modes:
  --mode mock_quota   Inject fake 429 errors on the primary call so EVERY
                      request walks the failover chain. Verifies wiring + chain
                      order without consuming real API quota.
  --mode live         Send real requests through call_node, observe which
                      profile hits a real rate-limit first and how the chain
                      handles it.

Run directly without starting the server:

  py tools\\stress_test.py --role dispatcher --n 5 --concurrency 3 --mode mock_quota

Or against a running server (uses the /api/stress/run endpoint):

  py tools\\stress_test.py --via-api --n 10 --mode live --url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Windows consoles default to cp950/cp1252 and choke on the report glyphs.
# Force UTF-8 unconditionally — text output only, no binary stream side effects.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

# Make the repo root importable when run from tools/
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _build_mock_429() -> Exception:
    """Build an httpx.HTTPStatusError(429) for inject_error."""
    import httpx
    req = httpx.Request("POST", "https://mock/")
    resp = httpx.Response(429, request=req, text="mock quota (stress test)")
    return httpx.HTTPStatusError("mock 429", request=req, response=resp)


async def run_direct(args):
    """Drive call_node directly — no FastAPI in the loop."""
    # Load .env exactly like app.py does
    env_path = REPO_ROOT / "config" / ".env"
    if env_path.exists():
        import os
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    from trinity_console import TrinityConsole

    console = TrinityConsole(REPO_ROOT / "config", REPO_ROOT / "data")

    sem = asyncio.Semaphore(args.concurrency)
    results = []
    t_start = time.time()

    async def _one(i):
        attempts: list = []
        async with sem:
            t0 = time.time()
            ok = False
            err = None
            try:
                inject = _build_mock_429() if args.mode == "mock_quota" else None
                await console.call_node(
                    args.role,
                    user_input=args.prompt,
                    protocol_text="",
                    extra_context="",
                    attempts_out=attempts,
                    inject_error=inject,
                )
                ok = True
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:200]}"
            results.append({
                "i": i,
                "ok": ok,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
                "error": err,
                "attempts": attempts,
            })

    await asyncio.gather(*(_one(i) for i in range(args.n)))
    total_ms = round((time.time() - t_start) * 1000, 1)
    _print_report(results, console.health.snapshot(), args, total_ms)


async def run_via_api(args):
    """Hit the running server's /api/stress/run endpoint."""
    import httpx
    url = args.url.rstrip("/") + "/api/stress/run"
    payload = {
        "role": args.role,
        "n": args.n,
        "concurrency": args.concurrency,
        "mode": args.mode,
        "prompt": args.prompt,
    }
    print(f"→ POST {url}  {json.dumps(payload)}")
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
    _print_report(data["results"], data["health"], args, data["total_ms"])


def _print_report(results, health, args, total_ms):
    success = sum(1 for r in results if r["ok"])
    fail = len(results) - success
    print()
    print("═" * 72)
    print(f"Stress test report — role={args.role}  mode={args.mode}  n={args.n}  concurrency={args.concurrency}")
    print("═" * 72)
    print(f"  ✓ success: {success}   ✗ fail: {fail}   total elapsed: {total_ms} ms")
    print()

    # Per-profile aggregation
    by_profile = {}
    for r in results:
        for a in r["attempts"]:
            prof = a.get("profile", "?")
            slot = by_profile.setdefault(prof, {"ok": 0, "fail": 0, "triggers": {}})
            if a.get("trigger") == "ok":
                slot["ok"] += 1
            else:
                slot["fail"] += 1
                t = a.get("trigger", "?")
                slot["triggers"][t] = slot["triggers"].get(t, 0) + 1

    if by_profile:
        print(f"  {'Profile':<22} {'OK':>5} {'Fail':>6}  Triggers")
        print(f"  {'-'*22} {'-'*5} {'-'*6}  {'-'*30}")
        for prof, s in by_profile.items():
            triggers = ", ".join(f"{t}={c}" for t, c in s["triggers"].items()) or "—"
            print(f"  {prof:<22} {s['ok']:>5} {s['fail']:>6}  {triggers}")
        print()

    # Health snapshot
    if health:
        print(f"  {'Profile':<22} {'Succ':>5} {'Fail':>5} {'Latency':>9}  {'Cooling':>9}")
        print(f"  {'-'*22} {'-'*5} {'-'*5} {'-'*9}  {'-'*9}")
        for name, h in health.items():
            cool = f"{h['cooldown_remaining_s']}s" if h.get("cooling") else "—"
            print(f"  {name:<22} {h['success']:>5} {h['fail']:>5} {h['last_latency_ms']:>7} ms  {cool:>9}")
        print()

    # Per-request trail (first 12)
    print("  Request trail (first 12):")
    for r in results[:12]:
        trail = " → ".join(
            f"[{a.get('profile','?')}{'*' if a.get('is_primary') else ''} {a.get('trigger','?')}]"
            for a in r["attempts"]
        )
        mark = "✓" if r["ok"] else "✗"
        print(f"    #{r['i']:>3} {mark} {r['elapsed_ms']:>7} ms  {trail}")
    if len(results) > 12:
        print(f"    ... ({len(results) - 12} more)")


def main():
    p = argparse.ArgumentParser(description="Stress test the Trinity failover chain")
    p.add_argument("--role", default="dispatcher",
                   choices=["dispatcher", "delabeling", "explanation", "filter",
                            "father", "son", "spirit", "council"],
                   help="Which node to hit (default: dispatcher — cheapest)")
    p.add_argument("--n", type=int, default=5, help="Total requests to fire")
    p.add_argument("--concurrency", type=int, default=3, help="Parallel in-flight")
    p.add_argument("--mode", default="mock_quota", choices=["mock_quota", "live"],
                   help="mock_quota injects fake 429 (safe). live spends real quota.")
    p.add_argument("--prompt", default="ping", help="User input for the node")
    p.add_argument("--via-api", action="store_true",
                   help="Hit a running server's /api/stress/run instead of importing direct")
    p.add_argument("--url", default="http://127.0.0.1:8000",
                   help="Server URL when --via-api is set")
    args = p.parse_args()

    if args.via_api:
        asyncio.run(run_via_api(args))
    else:
        asyncio.run(run_direct(args))


if __name__ == "__main__":
    main()
