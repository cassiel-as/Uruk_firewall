"""Review and promote privacy-gated controller learning candidates."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.controller_learning import STATUSES, learning_queue_summary  # noqa: E402
from training.dataset_validator import validate_controller_decision  # noqa: E402


BASE = ROOT / "data" / "controller_learning"


def _paths(status: str = "", *, base: Path = BASE) -> list[Path]:
    statuses = [status] if status else list(STATUSES)
    output: list[Path] = []
    for name in statuses:
        directory = Path(base) / name
        if directory.exists():
            output.extend(sorted(directory.glob("learn_*.json")))
    return output


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def summary(*, base: Path = BASE) -> dict[str, Any]:
    return learning_queue_summary(Path(base).parent.parent)


def list_records(status: str, limit: int, *, base: Path = BASE) -> list[dict[str, Any]]:
    records = [_load(path) for path in _paths(status, base=base)]
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    records.sort(key=lambda item: (
        priority_order.get(str(item.get("priority")), 9),
        str(item.get("created_at") or ""),
    ))
    return records[:max(1, limit)]


def review(
    candidate_id: str,
    status: str,
    *,
    reviewer: str,
    split: str,
    note: str,
    base: Path = BASE,
) -> dict[str, Any]:
    if status not in {"approved", "rejected"}:
        raise ValueError("review status must be approved or rejected")
    base = Path(base)
    source = base / "pending" / f"{candidate_id}.json"
    if not source.exists():
        raise FileNotFoundError(f"Pending candidate not found: {candidate_id}")
    record = _load(source)
    user_input = str((record.get("input") or {}).get("user_input") or "")
    if not 1 <= len(user_input) <= 4000:
        raise ValueError("Candidate input must contain 1..4000 sanitized characters.")
    reference_errors = validate_controller_decision(record.get("reference"))
    if reference_errors:
        raise ValueError("Candidate reference decision is invalid: " + "; ".join(reference_errors))
    provenance = record.get("provenance") or {}
    if provenance.get("type") == "data_factory" and split != "train":
        raise ValueError("Data Factory candidates derived from train sources may only be approved into train.")
    record["status"] = status
    record["review"] = {
        "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reviewer": reviewer,
        "note": note,
        "training_split": split if status == "approved" else None,
    }
    destination_dir = base / status
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    source.unlink()
    return {
        "candidate_id": candidate_id,
        "status": status,
        "training_split": split if status == "approved" else None,
        "path": str(destination),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Review accumulated URUK controller learning candidates.")
    sub = parser.add_subparsers(dest="command", required=True)
    summary_parser = sub.add_parser("summary")
    summary_parser.add_argument("--json", action="store_true")
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--status", choices=STATUSES, default="pending")
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.add_argument("--json", action="store_true")
    for command in ("approve", "reject"):
        review_parser = sub.add_parser(command)
        review_parser.add_argument("candidate_id")
        review_parser.add_argument("--reviewer", default="operator")
        review_parser.add_argument("--note", default="")
        review_parser.add_argument("--split", choices=("train", "validation", "test"), default="train")
        review_parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.command == "summary":
        result: Any = summary()
    elif args.command == "list":
        result = list_records(args.status, args.limit)
    else:
        result = review(
            args.candidate_id,
            "approved" if args.command == "approve" else "rejected",
            reviewer=args.reviewer,
            split=args.split,
            note=args.note,
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "summary":
        print(f"Controller learning queue: {result['record_count']} records, {result['occurrence_count']} occurrences")
        print(f"  status: {result['status_counts']}")
        print(f"  priority: {result['priority_counts']}")
    elif args.command == "list":
        for record in result:
            print(
                f"{record['candidate_id']} {record['priority']} "
                f"x{record.get('occurrence_count', 1)} {record['input']['user_input'][:120]}"
            )
    else:
        print(f"{result['candidate_id']} -> {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
