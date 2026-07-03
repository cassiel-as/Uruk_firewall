"""
Generated runtime summary indexes for URUK Trinity Console.

This module turns large runtime artifacts into compact Markdown indexes that
can safely enter RAG. Raw experiment reports, harness JSON, and self-upgrade
plans stay available on disk, but the main knowledge layer only receives the
stable summaries generated here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


ROOT = Path(__file__).parent.parent
INDEX_DIR = ROOT / "data" / "index"

EXPERIMENT_INDEX = INDEX_DIR / "EXPERIMENT_INDEX.md"
HARNESS_EPISODE_INDEX = INDEX_DIR / "HARNESS_EPISODE_INDEX.md"
UPGRADE_HISTORY_INDEX = INDEX_DIR / "UPGRADE_HISTORY_INDEX.md"


def _rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(_read_text(path))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _clean_line(value: Any) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    text = text.strip("║│┃┆┊┇┋| ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clip(value: Any, limit: int = 220) -> str:
    text = _clean_line(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _compact_list(values: Any, *, limit: int = 5) -> str:
    if not values:
        return "none"
    if isinstance(values, str):
        return _clip(values, 180)
    if not isinstance(values, Iterable):
        return _clip(values, 180)
    items = []
    for value in values:
        if isinstance(value, Mapping):
            item = (
                value.get("name")
                or value.get("id")
                or value.get("suggested_name")
                or value.get("title")
                or value.get("action")
                or value.get("description")
            )
        else:
            item = value
        if item is not None:
            items.append(_clip(item, 80))
        if len(items) >= limit:
            break
    more = ""
    try:
        total = len(values)  # type: ignore[arg-type]
    except Exception:
        total = len(items)
    if total > len(items):
        more = f" (+{total - len(items)} more)"
    return ", ".join(items) + more if items else "none"


def _get_nested(data: Mapping[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, Mapping):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _first_present(*values: Any, default: str = "n/a") -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return default


def _latest_source_mtime(paths: Sequence[Path]) -> str:
    mtimes = [p.stat().st_mtime for p in paths if p.exists()]
    if not mtimes:
        return "none"
    return datetime.fromtimestamp(max(mtimes)).isoformat(timespec="seconds")


def _extract_field(text: str, labels: Sequence[str]) -> str:
    wanted = {label.casefold(): label for label in labels}
    for raw_line in text.splitlines():
        line = _clean_line(raw_line)
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        if left.casefold().strip() in wanted:
            return _clip(right, 180)
    return "n/a"


def _extract_after_marker(text: str, marker: str, *, max_lines: int = 4) -> str:
    lines = text.splitlines()
    marker_key = marker.casefold()
    for index, raw_line in enumerate(lines):
        if marker_key not in raw_line.casefold():
            continue
        picked: List[str] = []
        for candidate in lines[index + 1 : index + 24]:
            line = _clean_line(candidate)
            if not line or line in {"---", "==="}:
                continue
            if line.startswith("[") and line.endswith("]"):
                continue
            picked.append(line)
            if len(picked) >= max_lines:
                break
        return _clip(" ".join(picked), 420)
    return "n/a"


def build_experiment_index(root: Path = ROOT) -> str:
    root = Path(root)
    paths = sorted((root / "data" / "experiments").glob("*.md"))
    lines = [
        "# URUK Experiment Summary Index",
        "",
        "Purpose: compact RAG entry point for Black Box Lab experiment records.",
        f"Source count: {len(paths)}",
        f"Latest source mtime: {_latest_source_mtime(paths)}",
        "",
        "Raw experiment files remain query-only evidence. This index carries the",
        "searchable summary fields needed for routing, comparison, and recall.",
        "",
    ]
    for path in paths:
        text = _read_text(path)
        rel = _rel(path, root)
        classification = _extract_field(text, ["CLASSIFICATION"])
        timestamp = _extract_field(text, ["TIMESTAMP"])
        mode = _extract_field(text, ["EXPERIMENT MODE"])
        primary_domain = _extract_field(text, ["Primary domain", "PRIMARY SUBJECT"])
        objective = _extract_field(text, ["Primary alignment objective", "Primary safety metric"])
        conclusion = _extract_after_marker(text, "CONCLUSION")
        lines.extend(
            [
                f"## {path.stem}",
                f"- path: `{rel}`",
                f"- size_bytes: {path.stat().st_size}",
                f"- classification: {classification}",
                f"- timestamp: {timestamp}",
                f"- mode: {mode}",
                f"- primary_domain: {primary_domain}",
                f"- objective_or_metric: {objective}",
                f"- conclusion_preview: {conclusion}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _episode_sort_key(item: Mapping[str, Any]) -> str:
    return str(item.get("created_at") or item.get("path") or "")


def _load_harness_episodes(root: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in sorted((root / "data" / "harness_episodes").glob("**/*.json")):
        data = _read_json(path)
        if data is None:
            continue
        data["_path"] = path
        records.append(data)
    return sorted(records, key=_episode_sort_key, reverse=True)


def build_harness_episode_index(root: Path = ROOT, *, limit: int = 80) -> str:
    root = Path(root)
    records = _load_harness_episodes(root)
    paths = [record["_path"] for record in records]
    mode_counts: Counter[str] = Counter()
    dispatch_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    for record in records:
        run = record.get("run") or {}
        dispatch = _get_nested(record, ["context", "dispatch"], {})
        mode_counts[str(_first_present(run.get("pipeline_mode"), default="unknown"))] += 1
        dispatch_counts[str(_first_present(dispatch.get("mode"), default="unknown"))] += 1
        route = _first_present(
            _get_nested(record, ["run", "cost_metrics", "route_kind"]),
            _get_nested(record, ["context", "dispatch", "cost_metrics", "route_kind"]),
            default="unknown",
        )
        route_counts[str(route)] += 1

    lines = [
        "# URUK Harness Episode Summary Index",
        "",
        "Purpose: compact RAG entry point for machine-readable conversation episodes.",
        f"Source count: {len(records)}",
        f"Latest source mtime: {_latest_source_mtime(paths)}",
        f"Pipeline modes: {_compact_counter(mode_counts)}",
        f"Dispatch modes: {_compact_counter(dispatch_counts)}",
        f"Route kinds: {_compact_counter(route_counts)}",
        "",
        "Each entry summarizes routing, knowledge health, coordinate output eval,",
        "density audit, and council outcome without indexing the full JSON payload.",
        "",
    ]
    for record in records[:limit]:
        path = record["_path"]
        rel = _rel(path, root)
        run = record.get("run") or {}
        context = record.get("context") or {}
        dispatch = context.get("dispatch") or {}
        validators = record.get("validators") or {}
        coordinate_eval = (
            validators.get("coordinate_output_eval")
            or validators.get("coordinate_eval")
            or {}
        )
        density = (
            validators.get("output_density_audit")
            or validators.get("density_audit")
            or {}
        )
        council = validators.get("council_decision") or {}
        health = _get_nested(context, ["knowledge", "health"], {})
        rag = health.get("rag") if isinstance(health, Mapping) else {}
        created_at = _first_present(record.get("created_at"), run.get("timestamp"))
        route_kind = _first_present(
            _get_nested(run, ["cost_metrics", "route_kind"]),
            _get_nested(dispatch, ["cost_metrics", "route_kind"]),
            default="n/a",
        )
        lines.extend(
            [
                f"## {record.get('episode_id') or path.stem}",
                f"- path: `{rel}`",
                f"- created_at: {created_at}",
                (
                    "- route: "
                    f"pipeline={_first_present(run.get('pipeline_mode'))}; "
                    f"dispatch={_first_present(dispatch.get('mode'))}; "
                    f"route_kind={route_kind}; "
                    f"model_tier={_first_present(run.get('model_tier'), dispatch.get('model_tier'))}"
                ),
                f"- input_preview: {_clip(_first_present(run.get('effective_input'), run.get('input'), default=''), 220)}",
                (
                    "- knowledge: "
                    f"clean={_first_present(health.get('clean') if isinstance(health, Mapping) else None)}; "
                    f"rag_chunks={_first_present(rag.get('n_chunks') if isinstance(rag, Mapping) else None)}; "
                    f"refs={_compact_list(dispatch.get('references'), limit=5)}"
                ),
                (
                    "- coordinate_output_eval: "
                    f"use={_first_present(coordinate_eval.get('coordinate_use'))}; "
                    f"score={_first_present(coordinate_eval.get('score'))}; "
                    f"selected={_compact_list(coordinate_eval.get('selected_card_ids'), limit=5)}; "
                    f"missing={_first_present(coordinate_eval.get('missing_count'))}"
                ),
                (
                    "- density_audit: "
                    f"density={_first_present(density.get('density'))}; "
                    f"candidates={_first_present(density.get('candidate_count'))}"
                ),
                (
                    "- council: "
                    f"verdict={_first_present(council.get('verdict'))}; "
                    f"primary_dimension={_clip(_first_present(council.get('primary_dimension'), default=''), 160)}"
                ),
                "",
            ]
        )
    if len(records) > limit:
        lines.append(f"Skipped older episodes: {len(records) - limit}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _compact_counter(counter: Counter[str], *, limit: int = 8) -> str:
    if not counter:
        return "none"
    parts = [f"{key}={count}" for key, count in counter.most_common(limit)]
    extra = sum(counter.values()) - sum(count for _, count in counter.most_common(limit))
    if extra:
        parts.append(f"other={extra}")
    return ", ".join(parts)


def _load_upgrade_plans(root: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in sorted((root / "data" / "upgrade_plans").glob("*.json")):
        data = _read_json(path)
        if data is None:
            continue
        data["_path"] = path
        records.append(data)
    return sorted(records, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def _load_upgrade_reports(root: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in sorted((root / "data" / "upgrade_reports").glob("*.json")):
        data = _read_json(path)
        if data is None:
            continue
        data["_path"] = path
        records.append(data)
    return sorted(records, key=lambda item: str(item.get("generated_at") or ""), reverse=True)


def _load_upgrade_log(root: Path) -> List[Dict[str, Any]]:
    path = root / "data" / "upgrade_log.jsonl"
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in _read_text(path).splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _names_from_tool_specs(value: Any) -> str:
    if not value:
        return "none"
    return _compact_list(value, limit=6)


def _gap_summary(value: Any) -> str:
    if not value:
        return "none"
    if not isinstance(value, list):
        return _clip(value, 240)
    parts = []
    for gap in value[:5]:
        if isinstance(gap, Mapping):
            priority = gap.get("priority") or "n/a"
            name = gap.get("id") or gap.get("suggested_name") or gap.get("description")
            parts.append(f"{priority}:{_clip(name, 80)}")
        else:
            parts.append(_clip(gap, 80))
    if len(value) > len(parts):
        parts.append(f"+{len(value) - len(parts)} more")
    return ", ".join(parts) if parts else "none"


def build_upgrade_history_index(root: Path = ROOT, *, plan_limit: int = 40) -> str:
    root = Path(root)
    plans = _load_upgrade_plans(root)
    reports = _load_upgrade_reports(root)
    log_records = _load_upgrade_log(root)
    paths = [record["_path"] for record in plans + reports]
    log_path = root / "data" / "upgrade_log.jsonl"
    if log_path.exists():
        paths.append(log_path)

    status_counts = Counter(str(plan.get("status") or "unknown") for plan in plans)
    mode_counts = Counter(str(plan.get("mode") or "unknown") for plan in plans)
    latest_report = reports[0] if reports else {}
    latest_plan = plans[0] if plans else {}

    lines = [
        "# URUK Self-Upgrade History Index",
        "",
        "Purpose: compact RAG entry point for self-upgrade plans, reports, and logs.",
        f"Plan count: {len(plans)}",
        f"Report count: {len(reports)}",
        f"Log event count: {len(log_records)}",
        f"Latest source mtime: {_latest_source_mtime(paths)}",
        f"Plan statuses: {_compact_counter(status_counts)}",
        f"Plan modes: {_compact_counter(mode_counts)}",
        "",
    ]
    if latest_report:
        summary = latest_report.get("summary") or {}
        latest_report_path = latest_report["_path"]
        lines.extend(
            [
                "## Latest Report",
                f"- path: `{_rel(latest_report_path, root)}`",
                f"- report_id: {latest_report.get('report_id')}",
                f"- generated_at: {latest_report.get('generated_at')}",
                f"- status: {latest_report.get('status')}",
                f"- summary: {_clip(json.dumps(summary, ensure_ascii=False), 360)}",
                f"- action_items: {_compact_list(latest_report.get('action_items'), limit=4)}",
                "",
            ]
        )
    if latest_plan:
        lines.extend(
            [
                "## Latest Plan",
                f"- path: `{_rel(latest_plan['_path'], root)}`",
                f"- plan_id: {latest_plan.get('plan_id')}",
                f"- created_at: {latest_plan.get('created_at')}",
                f"- mode: {latest_plan.get('mode')}",
                f"- status: {latest_plan.get('status')}",
                f"- installed_tools: {_compact_list(latest_plan.get('installed_tools'), limit=8)}",
                f"- tool_specs: {_names_from_tool_specs(latest_plan.get('tool_specs'))}",
                f"- gaps: {_gap_summary(latest_plan.get('gaps'))}",
                f"- summary: {_clip(latest_plan.get('summary'), 420)}",
                "",
            ]
        )

    lines.append("## Recent Plans")
    lines.append("")
    for plan in plans[:plan_limit]:
        lines.extend(
            [
                f"### {plan.get('plan_id') or Path(plan['_path']).stem}",
                f"- path: `{_rel(plan['_path'], root)}`",
                f"- created_at: {plan.get('created_at')}",
                f"- mode: {plan.get('mode')}; status: {plan.get('status')}; relay_target: {plan.get('relay_target')}",
                f"- installed_tools: {_compact_list(plan.get('installed_tools'), limit=6)}",
                f"- tool_specs: {_names_from_tool_specs(plan.get('tool_specs'))}",
                f"- gaps: {_gap_summary(plan.get('gaps'))}",
                f"- summary: {_clip(plan.get('summary'), 360)}",
                "",
            ]
        )
    if len(plans) > plan_limit:
        lines.append(f"Skipped older plans: {len(plans) - plan_limit}")
        lines.append("")

    if log_records:
        lines.append("## Upgrade Log Tail")
        lines.append("")
        for item in log_records[-10:]:
            lines.append(f"- {_clip(json.dumps(item, ensure_ascii=False), 360)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


INDEX_BUILDERS: Dict[Path, Callable[[Path], str]] = {
    EXPERIMENT_INDEX: build_experiment_index,
    HARNESS_EPISODE_INDEX: build_harness_episode_index,
    UPGRADE_HISTORY_INDEX: build_upgrade_history_index,
}


def build_all(root: Path = ROOT, *, write: bool = True) -> Dict[str, str]:
    root = Path(root)
    outputs: Dict[str, str] = {}
    for output_path, builder in INDEX_BUILDERS.items():
        target = root / _rel(output_path, ROOT)
        content = builder(root)
        outputs[_rel(target, root)] = content
        if write:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    return outputs


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build URUK runtime summary indexes")
    parser.add_argument("--build", action="store_true", help="Write generated indexes")
    parser.add_argument("--json", action="store_true", help="Print generated path metadata as JSON")
    parser.add_argument("--quiet", action="store_true", help="Suppress normal logs")
    args = parser.parse_args(argv)
    if not args.build:
        parser.print_help()
        return 1
    outputs = build_all(ROOT, write=True)
    if args.json:
        print(
            json.dumps(
                {path: {"chars": len(content)} for path, content in outputs.items()},
                ensure_ascii=False,
                indent=2,
            )
        )
    elif not args.quiet:
        for path, content in outputs.items():
            print(f"Wrote {path}: {len(content)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
