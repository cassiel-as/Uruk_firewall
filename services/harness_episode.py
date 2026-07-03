"""
Harness episode package writer for URUK Trinity Console.

The episode package is a machine-readable companion to the human Markdown
conversation archive. It gives evals, replay tooling, and regression gates a
stable object to inspect without parsing prose.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from services.knowledge_manifest import manifest_sha256
except Exception:  # pragma: no cover - episode writing must stay best-effort
    manifest_sha256 = None


SCHEMA_VERSION = "1.0"
MAX_STRING = 8000
MAX_COLLECTION = 50


def _sha256_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _compact(value: Any, *, max_string: int = MAX_STRING, depth: int = 0) -> Any:
    """Return a JSON-safe, bounded representation of arbitrary run data."""
    if depth > 8:
        return {"_truncated": "max_depth"}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= max_string:
            return value
        return {
            "text_preview": value[:max_string],
            "truncated": True,
            "original_chars": len(value),
            "sha256": _sha256_text(value),
        }
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= MAX_COLLECTION:
                out["_truncated_items"] = len(value) - MAX_COLLECTION
                break
            out[str(k)] = _compact(v, max_string=max_string, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        out = [
            _compact(item, max_string=max_string, depth=depth + 1)
            for item in seq[:MAX_COLLECTION]
        ]
        if len(seq) > MAX_COLLECTION:
            out.append({"_truncated_items": len(seq) - MAX_COLLECTION})
        return out
    return str(value)


def _rel(path: Optional[Path], base: Path) -> Optional[str]:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def _file_sha256_optional(path: Path) -> Optional[str]:
    try:
        if path.exists() and path.is_file():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None
    return None


def build_episode(result: Dict[str, Any], *, data_dir: Path, conversation_path: Path) -> Dict[str, Any]:
    """Build a bounded episode package from a Trinity run result."""
    data_dir = Path(data_dir)
    conversation_path = Path(conversation_path)
    council = result.get("council", "")
    father = result.get("father", "")
    son = result.get("son", "")
    spirit = result.get("spirit", "")
    dispatch = result.get("dispatch") or {}
    output_density = result.get("output_density_audit") or result.get("density_audit") or {}
    council_decision = result.get("council_decision") or {}
    coordinate_output_eval = result.get("coordinate_output_eval") or result.get("coordinate_eval") or {}
    cost_metrics = result.get("cost_metrics") or dispatch.get("cost_metrics") or {}
    context_budget = result.get("context_budget") or dispatch.get("context_budget") or {}
    inference_usage = result.get("inference_usage") or {}
    son_veto = result.get("son_veto_metadata") or {}
    spirit_meta = result.get("spirit_metadata") or {}
    root_dir = data_dir.parent
    rag_manifest_path = data_dir / "rag_index" / "manifest.json"
    knowledge_manifest_path = data_dir / "knowledge_manifest.json"
    knowledge_manifest_hash = None
    if manifest_sha256 is not None:
        try:
            knowledge_manifest_hash = manifest_sha256(root=root_dir)
        except Exception:
            knowledge_manifest_hash = None

    episode = {
        "schema_version": SCHEMA_VERSION,
        "episode_id": conversation_path.stem,
        "created_at": datetime.now().isoformat(),
        "artifacts": {
            "conversation_markdown": _rel(conversation_path, data_dir),
        },
        "run": {
            "timestamp": result.get("timestamp"),
            "pipeline_mode": result.get("pipeline_mode") or "auto",
            "selected_modes": _compact(result.get("selected_modes") or []),
            "execution_strategy": result.get("execution_strategy") or "",
            "input": _compact(result.get("input", "")),
            "effective_input": _compact(result.get("effective_input", "")),
            "input_sha256": _sha256_text(result.get("input", "")),
            "cost_metrics": _compact(cost_metrics),
            "context_budget": _compact(context_budget),
            "inference_usage": _compact(inference_usage, max_string=1000),
            "model_tier": result.get("model_tier") or dispatch.get("model_tier") or "",
            "escalation_level": result.get("escalation_level") if result.get("escalation_level") is not None else dispatch.get("escalation_level"),
        },
        "context": {
            "user_refs": _compact(result.get("user_refs") or []),
            "all_data_refs": _compact(result.get("all_data_refs") or []),
            "dispatch": {
                "mode": dispatch.get("mode"),
                "mode_rationale": dispatch.get("mode_rationale") or dispatch.get("rationale") or "",
                "references": _compact(dispatch.get("references") or []),
                "suggested_data_refs": _compact(dispatch.get("suggested_data_refs") or []),
                "data_rationale": dispatch.get("data_rationale") or "",
                "cost_metrics": _compact(cost_metrics),
                "context_budget": _compact(context_budget),
                "model_tier": result.get("model_tier") or dispatch.get("model_tier") or "",
                "escalation_level": result.get("escalation_level") if result.get("escalation_level") is not None else dispatch.get("escalation_level"),
            },
            "knowledge": {
                "manifest_path": _rel(knowledge_manifest_path, data_dir),
                "manifest_sha256": knowledge_manifest_hash,
                "rag_manifest_path": _rel(rag_manifest_path, data_dir),
                "rag_manifest_sha256": _file_sha256_optional(rag_manifest_path),
                "health": _compact(result.get("knowledge_health") or {}, max_string=1000),
                "trace": _compact(result.get("knowledge_trace") or [], max_string=1000),
            },
        },
        "stages": {
            "stage1": _compact(result.get("stage1") or {}),
            "stage2": _compact(result.get("stage2") or {}),
            "stage3": _compact(result.get("stage3") or {}),
        },
        "voices": {
            "father": {"sha256": _sha256_text(father), "preview": _compact(father, max_string=2000)},
            "son": {"sha256": _sha256_text(son), "preview": _compact(son, max_string=2000)},
            "spirit": {"sha256": _sha256_text(spirit), "preview": _compact(spirit, max_string=2000)},
            "council": {"sha256": _sha256_text(council), "preview": _compact(council, max_string=4000)},
        },
        "validators": {
            "output_density_audit": _compact(output_density),
            "density_audit": _compact(output_density),
            "council_decision": _compact(council_decision),
            "coordinate_output_eval": _compact(coordinate_output_eval),
            "coordinate_eval": _compact(coordinate_output_eval),
            "son_veto": _compact(son_veto),
            "spirit": _compact(spirit_meta),
            "father_paused": bool(result.get("father_paused", False)),
            "council_fusion_deterministic": bool(result.get("council_fusion_deterministic", False)),
        },
        "node_config": _compact(result.get("node_config") or {}),
    }

    proposed = output_density.get("proposed_path") if isinstance(output_density, dict) else None
    if proposed:
        episode["artifacts"]["density_proposed_path"] = str(proposed)
    return episode


def write_episode(
    result: Dict[str, Any],
    *,
    data_dir: Path,
    conversation_path: Path,
) -> Path:
    """Write an episode package and return its path."""
    data_dir = Path(data_dir)
    conversation_path = Path(conversation_path)
    date_dir = data_dir / "harness_episodes" / datetime.now().strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    path = date_dir / f"{conversation_path.stem}.json"
    episode = build_episode(result, data_dir=data_dir, conversation_path=conversation_path)
    episode["artifacts"]["episode_json"] = _rel(path, data_dir)
    path.write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
