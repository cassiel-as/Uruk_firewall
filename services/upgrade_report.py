"""Automated self-upgrade report generation.

The report is read-only: it gathers upgrade plans, upgrade logs, deterministic
gates, and prompt regression state, then writes a JSON + Markdown artifact for
operators and UI surfaces.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "upgrade_reports"
SCHEMA_VERSION = "1.0"
RECENT_PLAN_WINDOW_HOURS = 72.0


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _plan_files(root: Path) -> List[Path]:
    plans_dir = root / "data" / "upgrade_plans"
    if not plans_dir.exists():
        return []
    return sorted(plans_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)


def _compact_plan(data: Dict[str, Any], path: Path, root: Path) -> Dict[str, Any]:
    steps = data.get("steps") or []
    failed_steps = [s.get("action") for s in steps if s.get("status") == "failed"]
    running_steps = [s.get("action") for s in steps if s.get("status") == "running"]
    return {
        "plan_id": data.get("plan_id"),
        "mode": data.get("mode"),
        "relay_target": data.get("relay_target"),
        "status": data.get("status"),
        "created_at": data.get("created_at"),
        "summary": data.get("summary", ""),
        "gap_count": len(data.get("gaps") or []),
        "tool_spec_count": len(data.get("tool_specs") or []),
        "review_count": len(data.get("review_tool_specs") or []),
        "installed_tools": data.get("installed_tools") or [],
        "snapshots": data.get("snapshots") or {},
        "failed_steps": failed_steps,
        "running_steps": running_steps,
        "path": _rel(path, root),
    }


def collect_upgrade_plans(*, root: Path = ROOT, limit: int = 8) -> List[Dict[str, Any]]:
    root = Path(root)
    plans: List[Dict[str, Any]] = []
    for path in _plan_files(root)[: max(0, limit)]:
        data = _read_json(path)
        if data:
            plans.append(_compact_plan(data, path, root))
    return plans


def load_full_plan(plan_id: str, *, root: Path = ROOT) -> Optional[Dict[str, Any]]:
    safe = str(plan_id or "").strip()
    if not safe or "/" in safe or "\\" in safe or ".." in safe:
        return None
    return _read_json(Path(root) / "data" / "upgrade_plans" / f"{safe}.json")


def collect_upgrade_log(*, root: Path = ROOT, limit: int = 12) -> List[Dict[str, Any]]:
    path = Path(root) / "data" / "upgrade_log.jsonl"
    if not path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            entries.append({"parse_error": line[:240]})
    return list(reversed(entries))[: max(0, limit)]


def _run_gate_preflight() -> Dict[str, Any]:
    try:
        from upgrade_engine import run_upgrade_gate_preflight

        return run_upgrade_gate_preflight()
    except Exception as exc:
        return {
            "ok": None,
            "error": f"{type(exc).__name__}: {exc}",
            "checked_at": datetime.now().isoformat(),
        }


def _run_prompt_regression(root: Path) -> Dict[str, Any]:
    try:
        from services.prompt_regression import run_prompt_regression_check

        return run_prompt_regression_check(
            root=root,
            run_benchmark=True,
            run_quick_eval=True,
            compare_latest_episode=True,
            strict_episode=False,
        )
    except Exception as exc:
        return {
            "ok": None,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "checked_at": datetime.now().isoformat(),
        }


def _issue(priority: str, title: str, detail: str = "", action: str = "") -> Dict[str, str]:
    return {
        "priority": priority,
        "title": title,
        "detail": detail,
        "action": action,
    }


def _plan_age_hours(plan: Dict[str, Any], *, now: Optional[datetime] = None) -> Optional[float]:
    raw = str(plan.get("created_at") or "").strip()
    if not raw:
        return None
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return max(0.0, (current - created).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return None


def _is_recent_plan(plan: Dict[str, Any]) -> bool:
    age = _plan_age_hours(plan)
    return age is None or age <= RECENT_PLAN_WINDOW_HOURS


def derive_action_items(
    *,
    latest_plan: Optional[Dict[str, Any]],
    plans: Iterable[Dict[str, Any]],
    upgrade_log: Iterable[Dict[str, Any]],
    gates: Optional[Dict[str, Any]],
    prompt_regression: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    plan_list = list(plans)
    log_list = list(upgrade_log)

    if not latest_plan:
        items.append(_issue(
            "P1",
            "未有 self-upgrade plan",
            "data/upgrade_plans 未有可用計劃。",
            "先喺自我升級面板跑一次缺陷審計或互聯網學習。",
        ))
    else:
        status = str(latest_plan.get("status") or "")
        if status in {"failed", "error", "rolled_back"}:
            if _is_recent_plan(latest_plan):
                items.append(_issue(
                    "P0",
                    f"最新升級計劃狀態係 {status}",
                    latest_plan.get("summary", ""),
                    f"檢查 {latest_plan.get('plan_id')} 嘅 failed_steps / relay_error，再重跑或改 relay。",
                ))
            else:
                age = _plan_age_hours(latest_plan)
                items.append(_issue(
                    "P2",
                    f"最近一份升級計劃係歷史 {status}",
                    f"{latest_plan.get('summary', '')}（約 {round(age or 0)} 小時前）",
                    "當前 gates 如已通過，可開一份有明確目標嘅新計劃；歷史失敗保留作審計，不阻塞現在。",
                ))
        elif status == "review_required":
            items.append(_issue(
                "P0",
                "最新升級需要人工審核",
                "有工具 spec 被安全閘標記，需要操作者確認。",
                "只批准無檔案寫入、無 shell、無網絡、無 credential access 嘅 spec。",
            ))
        elif status in {"waiting_claude", "waiting_relay"}:
            items.append(_issue(
                "P1",
                "最新升級等待外部模型回覆",
                latest_plan.get("summary", ""),
                "確認 relay app 有運行，或改用 Codex / local 重新跑。",
            ))

        if latest_plan.get("failed_steps"):
            items.append(_issue(
                "P1",
                "升級計劃存在 failed steps",
                ", ".join(map(str, latest_plan.get("failed_steps") or [])),
                "打開 plan detail，先處理第一個 failed step。",
            ))

        if status == "done" and not latest_plan.get("installed_tools"):
            items.append(_issue(
                "P2",
                "最新計劃完成但未安裝工具",
                "可能只完成掃描/審核，未產生可安裝 spec。",
                "檢查 gaps 是否仍然有效；如有效就重跑設計 step。",
            ))

    recent_plans = [p for p in plan_list if _is_recent_plan(p)][:5]
    failed_recent = [p for p in recent_plans if p.get("status") in {"failed", "error", "rolled_back"}]
    if len(failed_recent) >= 2:
        items.append(_issue(
            "P1",
            "近期升級失敗率偏高",
            f"最近 {len(recent_plans)} 個近期計劃有 {len(failed_recent)} 個失敗/回滾。",
            "暫停自動 loop，先修 relay、validation 或 benchmark gate。",
        ))

    if gates:
        if gates.get("ok") is False:
            items.append(_issue(
                "P0",
                "self-upgrade 硬閘未通過",
                "knowledge audit、coordinate benchmark 或 quick_eval 其中一項失敗。",
                "先修硬閘；未通過前不要安裝新工具。",
            ))
        stability = gates.get("stability_golden") or {}
        if stability.get("passed") is False:
            items.append(_issue(
                "P0",
                "stability golden cases failed",
                ", ".join(map(str, stability.get("failed_cases") or [])),
                "先修 routing / Kairos / World / runtime identity contract，再重新跑 self-upgrade gate。",
            ))
        quick = gates.get("quick_eval") or {}
        if quick.get("skipped"):
            items.append(_issue(
                "P3",
                "quick_eval 未建立 baseline",
                quick.get("reason", ""),
                "需要量化 prompt/輸出品質時，先建立 quick_eval baseline。",
            ))
    quick_eval_skip_reported = any(item.get("title") == "quick_eval 未建立 baseline" for item in items)

    if prompt_regression:
        diff = prompt_regression.get("diff") or {}
        if prompt_regression.get("ok") is False:
            items.append(_issue(
                "P0",
                "prompt regression 失敗",
                ", ".join(prompt_regression.get("failures") or []),
                "不要合併相關改動，先修 failing gate。",
            ))
        if diff.get("prompt_changed"):
            items.append(_issue(
                "P1",
                "prompt/protocol bundle 有變動",
                "需要確認變動係預期，而唔係 accidental drift。",
                "review changed files；確認後更新 baseline。",
            ))
        if "quick_eval_skipped" in (prompt_regression.get("warnings") or []) and not quick_eval_skip_reported:
            items.append(_issue(
                "P3",
                "prompt regression quick_eval skipped",
                "目前只做到 deterministic gate，缺少輸出品質 baseline。",
                "需要更強輸出回歸時，補 quick_eval baseline。",
            ))

    if not log_list:
        items.append(_issue(
            "P2",
            "upgrade log 未有安裝記錄",
            "系統可以生成 plan，但未見成功寫入 installed tool audit log。",
            "完成一次可安裝、可 smoke test 嘅安全工具後確認 write_log step。",
        ))

    if not items:
        items.append(_issue(
            "P3",
            "未見阻塞問題",
            "硬閘、prompt regression、最新 plan 未顯示高風險問題。",
            "可以進入下一輪有目標嘅 audit/learn，避免無目的循環升級。",
        ))
    return items


def _priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(priority, 9)


def _overall_status(items: List[Dict[str, str]], gates: Dict[str, Any], prompt: Dict[str, Any]) -> str:
    if any(item.get("priority") == "P0" for item in items):
        return "blocked"
    if gates.get("ok") is False or prompt.get("ok") is False:
        return "blocked"
    if any(item.get("priority") in {"P1", "P2"} for item in items):
        return "attention"
    return "healthy"


def _format_bool(value: Any) -> str:
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    return "SKIP"


def render_markdown(report: Dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    latest = report.get("latest_plan") or {}
    gates = report.get("gates") or {}
    prompt = report.get("prompt_regression") or {}
    benchmark = ((prompt.get("checks") or {}).get("benchmark") or {})
    benchmark_cost = benchmark.get("cost_summary") or ((gates.get("benchmark") or {}).get("cost_summary") or {})
    quick = gates.get("quick_eval") or {}

    lines = [
        f"# URUK Self-Upgrade Report: {report.get('report_id')}",
        "",
        f"- generated_at: {report.get('generated_at')}",
        f"- status: {report.get('status')}",
        f"- plans_scanned: {summary.get('plan_count', 0)}",
        f"- upgrade_log_entries: {summary.get('upgrade_log_count', 0)}",
        f"- gates: {_format_bool(gates.get('ok'))}",
        f"- prompt_regression: {prompt.get('status', 'unknown')} ok={prompt.get('ok')}",
        "",
        "## Latest Plan",
    ]
    if latest:
        lines.extend([
            f"- plan_id: {latest.get('plan_id')}",
            f"- mode: {latest.get('mode')}",
            f"- relay_target: {latest.get('relay_target')}",
            f"- status: {latest.get('status')}",
            f"- installed_tools: {', '.join(latest.get('installed_tools') or []) or '(none)'}",
            f"- pre_install_snapshot: {((latest.get('snapshots') or {}).get('pre_install') or {}).get('path') or '(none)'}",
            f"- summary: {latest.get('summary') or '(empty)'}",
        ])
    else:
        lines.append("- (none)")

    lines.extend([
        "",
        "## Gates",
        f"- knowledge_audit: {_format_bool((gates.get('knowledge_audit') or {}).get('passed'))}",
        f"- coordinate_benchmark: {_format_bool((gates.get('benchmark') or {}).get('passed'))} "
        f"{(gates.get('benchmark') or {}).get('passed_count', '--')}/{(gates.get('benchmark') or {}).get('case_count', '--')}",
        f"- stability_golden: {_format_bool((gates.get('stability_golden') or {}).get('passed'))} "
        f"{(gates.get('stability_golden') or {}).get('passed_count', '--')}/{(gates.get('stability_golden') or {}).get('case_count', '--')}",
        f"- quick_eval: {_format_bool(quick.get('passed'))} {quick.get('reason') or ''}".rstrip(),
        f"- prompt_hash: {str((prompt.get('fingerprint') or {}).get('sha256') or '')[:12]}",
        f"- prompt_changed: {(prompt.get('diff') or {}).get('prompt_changed')}",
        f"- benchmark_cases: {benchmark.get('passed_count', '--')}/{benchmark.get('case_count', '--')}",
        f"- benchmark_cost: model_calls={benchmark_cost.get('estimated_model_calls', '--')} "
        f"api_calls={benchmark_cost.get('estimated_api_model_calls', '--')} "
        f"context_tokens={benchmark_cost.get('estimated_context_tokens', '--')}",
        "",
        "## Action Items",
    ])
    for item in sorted(report.get("action_items") or [], key=lambda x: _priority_rank(x.get("priority", ""))):
        detail_text = str(item.get("detail") or "").rstrip("。.! ")
        detail = f" — {detail_text}" if detail_text else ""
        action = f" Action: {item.get('action')}" if item.get("action") else ""
        lines.append(f"- [{item.get('priority')}] {item.get('title')}{detail}.{action}".rstrip())

    recent = report.get("recent_plans") or []
    if recent:
        lines.extend(["", "## Recent Plans"])
        for plan in recent[:6]:
            lines.append(
                f"- {plan.get('plan_id')} · {plan.get('mode')} · {plan.get('status')} · "
                f"installed={len(plan.get('installed_tools') or [])} · gaps={plan.get('gap_count')}"
            )

    return "\n".join(lines).rstrip() + "\n"


def _write_report(report: Dict[str, Any], *, root: Path) -> Dict[str, str]:
    reports_dir = Path(root) / "data" / "upgrade_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_id = report["report_id"]
    json_path = reports_dir / f"{report_id}.json"
    md_path = reports_dir / f"{report_id}.md"
    markdown = render_markdown(report)
    report["markdown"] = markdown
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return {"json_path": _rel(json_path, Path(root)), "markdown_path": _rel(md_path, Path(root))}


def generate_self_upgrade_report(
    *,
    root: Path = ROOT,
    plan_limit: int = 8,
    log_limit: int = 12,
    run_gates: bool = True,
    run_prompt_regression: bool = True,
    write: bool = True,
) -> Dict[str, Any]:
    root = Path(root)
    report_id = f"upgrade-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    plans = collect_upgrade_plans(root=root, limit=plan_limit)
    latest = plans[0] if plans else None
    upgrade_log = collect_upgrade_log(root=root, limit=log_limit)
    gates = _run_gate_preflight() if run_gates else {"ok": None, "skipped": True}
    prompt = _run_prompt_regression(root) if run_prompt_regression else {"ok": None, "status": "skipped"}
    action_items = derive_action_items(
        latest_plan=latest,
        plans=plans,
        upgrade_log=upgrade_log,
        gates=gates,
        prompt_regression=prompt,
    )
    status = _overall_status(action_items, gates, prompt)
    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "generated_at": datetime.now().isoformat(),
        "status": status,
        "ok": status != "blocked",
        "summary": {
            "plan_count": len(plans),
            "upgrade_log_count": len(upgrade_log),
            "latest_plan_id": latest.get("plan_id") if latest else None,
            "latest_plan_status": latest.get("status") if latest else None,
            "latest_plan_age_hours": round(_plan_age_hours(latest), 1) if latest and _plan_age_hours(latest) is not None else None,
            "latest_plan_is_recent": _is_recent_plan(latest) if latest else None,
            "gates_ok": gates.get("ok"),
            "prompt_regression_status": prompt.get("status"),
            "prompt_changed": (prompt.get("diff") or {}).get("prompt_changed"),
            "action_count": len(action_items),
        },
        "latest_plan": latest,
        "recent_plans": plans,
        "upgrade_log": upgrade_log,
        "gates": gates,
        "prompt_regression": prompt,
        "action_items": sorted(action_items, key=lambda x: _priority_rank(x.get("priority", ""))),
    }
    if write:
        report["files"] = _write_report(report, root=root)
    else:
        report["markdown"] = render_markdown(report)
    return report


def list_reports(*, root: Path = ROOT, limit: int = 20) -> List[Dict[str, Any]]:
    reports_dir = Path(root) / "data" / "upgrade_reports"
    if not reports_dir.exists():
        return []
    result: List[Dict[str, Any]] = []
    for path in sorted(reports_dir.glob("upgrade-report-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        data = _read_json(path) or {}
        result.append({
            "report_id": data.get("report_id") or path.stem,
            "generated_at": data.get("generated_at"),
            "status": data.get("status"),
            "ok": data.get("ok"),
            "summary": data.get("summary") or {},
            "files": data.get("files") or {"json_path": _rel(path, Path(root))},
        })
    return result


def load_report(report_id: str, *, root: Path = ROOT) -> Optional[Dict[str, Any]]:
    safe = str(report_id or "").strip()
    if not safe or "/" in safe or "\\" in safe or ".." in safe:
        return None
    if safe.endswith(".json"):
        safe = safe[:-5]
    return _read_json(Path(root) / "data" / "upgrade_reports" / f"{safe}.json")
