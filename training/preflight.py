"""Preflight checks for local URUK Controller QLoRA training."""
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
REQUIRED_PACKAGES = ("torch", "transformers", "datasets", "peft", "trl", "bitsandbytes", "accelerate")


def _gpu_status() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=True,
        )
        first = proc.stdout.strip().splitlines()[0]
        name, total, free, driver = [item.strip() for item in first.split(",", maxsplit=3)]
        return {
            "visible": True,
            "name": name,
            "memory_total_mb": int(total),
            "memory_free_mb": int(free),
            "driver_version": driver,
        }
    except Exception as exc:
        return {"visible": False, "error": f"{type(exc).__name__}: {exc}"}


def run_preflight(data_dir: Path = ROOT / "training" / "generated") -> dict[str, Any]:
    package_status = {name: bool(importlib.util.find_spec(name)) for name in REQUIRED_PACKAGES}
    torch_status: dict[str, Any] = {"imported": False, "cuda_available": False}
    if package_status["torch"]:
        try:
            import torch

            torch_status = {
                "imported": True,
                "version": torch.__version__,
                "cuda_build": torch.version.cuda,
                "cuda_available": bool(torch.cuda.is_available()),
                "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            }
        except Exception as exc:
            torch_status = {"imported": False, "cuda_available": False, "error": f"{type(exc).__name__}: {exc}"}

    data_dir = Path(data_dir)
    manifest_path = data_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    split_counts = manifest.get("split_counts") or {}
    data_ready = (
        int(manifest.get("example_count") or 0) >= 150
        and int(split_counts.get("validation") or 0) >= 20
        and int(split_counts.get("test") or 0) >= 30
    )
    python_supported = (3, 10) <= sys.version_info[:2] <= (3, 12)
    gpu = _gpu_status()
    checks = {
        "python_supported": python_supported,
        "packages_installed": all(package_status.values()),
        "torch_cuda_available": bool(torch_status.get("cuda_available")),
        "gpu_memory_sufficient": bool(gpu.get("visible")) and int(gpu.get("memory_total_mb") or 0) >= 6000,
        "dataset_ready": data_ready,
    }
    return {
        "schema_version": "uruk_controller_training_preflight.v1",
        "passed": all(checks.values()),
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "supported_range": "3.10-3.12",
        },
        "packages": package_status,
        "torch": torch_status,
        "gpu": gpu,
        "dataset": {
            "path": str(data_dir),
            "example_count": manifest.get("example_count"),
            "split_counts": split_counts,
        },
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether local QLoRA training can start safely.")
    parser.add_argument("--data-dir", default=str(ROOT / "training" / "generated"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_preflight(Path(args.data_dir))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if report["passed"] else "BLOCKED"
        print(f"URUK controller training preflight {status}")
        for name, passed in report["checks"].items():
            print(f"  {'ok' if passed else 'BLOCK'} {name}")
        print(f"  python: {report['python']['version']} ({report['python']['executable']})")
        print(f"  torch: {report['torch']}")
        print(f"  gpu: {report['gpu']}")
        print(f"  dataset: {report['dataset']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
