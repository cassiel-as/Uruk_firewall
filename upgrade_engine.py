"""
URUK Trinity Console — Upgrade Engine
v1.0

分工架構：
  system steps  → URUK Python 代碼自動執行（掃描/驗證/安裝/測試）
  claude steps  → 發送到 Claude（只需要設計工具代碼）

計劃書格式（JSONL，每個計劃一個 JSON 文件）：
  data/upgrade_plans/<plan_id>.json
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.relay_protocol import tool_spec_block, upgrade_output_contract
from services.knowledge_manifest import audit_knowledge
from services.system_identity import get_identity, refresh_identity
from services.performance_reality import record_fidelity_snapshot, fidelity_delta as get_fidelity_delta
from services.density_bridge import density_gaps_for_upgrade
from services.upgrade_self_audit import run_upgrade_self_audit, SelfAuditResult

APP_ROOT       = Path(__file__).parent
DATA_DIR       = APP_ROOT / "data"
PLANS_DIR      = DATA_DIR / "upgrade_plans"
LOG_PATH       = DATA_DIR / "upgrade_log.jsonl"
CUSTOM_DIR     = APP_ROOT / "services" / "custom_tools"
BASELINES_PATH = DATA_DIR / "upgrade_baselines.json"

DEFAULT_EXECUTION_CONTRACT = {
    "executor_role": (
        "本地細模型只負責每一步選擇/確認系統 action，同補充安全理由；"
        "真正寫檔、驗證、熱載入由 deterministic upgrade_engine 執行。"
    ),
    "global_allowed_actions": [
        "validate_code",
        "install_tools",
        "hot_reload",
        "smoke_test",
        "write_log",
    ],
    "safety_rules": [
        "不可改變 planner 指定嘅 action 次序",
        "不可新增工具安裝步驟以外嘅文件寫入",
        "如果工具代碼有刪檔、shell、網絡下載、憑證存取等高風險行為，要求人類確認",
    ],
    "stop_conditions": [
        "validation 全部失敗",
        "細模型要求人類確認",
        "細模型嘗試越權 action",
    ],
}

# ─────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────

@dataclass
class PlanStep:
    id: int
    executor: str          # "system" | relay target name
    action: str
    status: str = "pending"  # pending / running / done / failed / skipped
    description: str = ""
    executor_rule: str = ""
    allowed_actions: List[str] = field(default_factory=list)
    success_criteria: str = ""
    input: Any = None       # data passed into this step
    output: Any = None      # data produced by this step
    error: str = ""
    duration_ms: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class UpgradePlan:
    plan_id: str
    mode: str               # "audit" | "learn"
    relay_target: str       # "claude" | "claude_code" | "chatgpt" | "codex" | "local"
    created_at: str
    status: str = "created" # created / running / waiting_relay / installing / done / failed
    steps: List[PlanStep] = field(default_factory=list)
    summary: str = ""       # human-readable summary
    gaps: List[Dict] = field(default_factory=list)
    tool_specs: List[Dict] = field(default_factory=list)  # filled by Claude
    review_tool_specs: List[Dict] = field(default_factory=list)  # high-risk specs awaiting human approval
    installed_tools: List[str] = field(default_factory=list)
    snapshots: Dict[str, Any] = field(default_factory=dict)
    execution_contract: Dict = field(default_factory=dict)
    executor_events: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d

    def save(self) -> Path:
        PLANS_DIR.mkdir(parents=True, exist_ok=True)
        path = PLANS_DIR / f"{self.plan_id}.json"
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def load(plan_id: str) -> "UpgradePlan":
        path = PLANS_DIR / f"{plan_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        steps = [PlanStep(**s) for s in data.pop("steps", [])]
        plan = UpgradePlan(**data)
        plan.steps = steps
        return plan

    def get_step(self, action: str) -> Optional[PlanStep]:
        return next((s for s in self.steps if s.action == action), None)

    def update_step(
        self,
        action: str,
        status: str,
        input: Any = None,
        output: Any = None,
        error: str = "",
    ) -> None:
        s = self.get_step(action)
        if s:
            s.status = status
            if input is not None:
                s.input = input
            if output is not None:
                s.output = output
            if error:
                s.error = error
        self.save()


# ─────────────────────────────────────────────────────────────────
# System steps (URUK executes autonomously)
# ─────────────────────────────────────────────────────────────────

def _make_step(
    id: int,
    executor: str,
    action: str,
    description: str,
    *,
    executor_rule: str = "",
    success_criteria: str = "",
) -> PlanStep:
    allowed = [action] if executor == "system" else []
    return PlanStep(
        id,
        executor,
        action,
        description=description,
        executor_rule=executor_rule,
        allowed_actions=allowed,
        success_criteria=success_criteria,
    )


def step_scan_tools() -> Dict:
    """掃描現有工具，返回工具清單 + 類別分佈。"""
    from services.computer_tools import TOOL_REGISTRY
    tools = list(TOOL_REGISTRY.keys())
    cats: Dict[str, List[str]] = {}
    for name, spec in TOOL_REGISTRY.items():
        cats.setdefault(spec.category, []).append(name)
    return {"count": len(tools), "tools": tools, "by_category": cats}


def step_scan_vessel() -> Dict:
    """Scan runtime hardware and derive vessel capabilities."""
    from services.vessel_scanner import get_vessel_profile

    return get_vessel_profile().to_dict()


def step_scan_sessions(max_n: int = 10) -> Dict:
    """掃描最近 N 個 harness episode，提取失敗模式 + 常見操作。"""
    episode_dir = DATA_DIR / "harness_episodes"
    snippets = []
    errors = []
    source = "harness_episodes"

    if episode_dir.exists():
        files = sorted(episode_dir.glob("**/*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        for ep_path in files[:max_n]:
            try:
                data = json.loads(ep_path.read_text(encoding="utf-8"))
                run = data.get("run") or {}
                context = data.get("context") or {}
                knowledge = context.get("knowledge") or {}
                validators = data.get("validators") or {}
                density = validators.get("output_density_audit") or validators.get("density_audit") or {}
                council = validators.get("council_decision") or {}
                coordinate_output_eval = (
                    validators.get("coordinate_output_eval")
                    or validators.get("coordinate_eval")
                    or {}
                )
                health = knowledge.get("health") or {}
                trace = knowledge.get("trace") or []

                inp = str(run.get("input") or "")[:240]
                selected_modes = run.get("selected_modes") or []
                mode = run.get("pipeline_mode") or (
                    "+".join(selected_modes) if isinstance(selected_modes, list) else ""
                )

                error_reasons: List[str] = []
                density_errors = density.get("errors") if isinstance(density, dict) else None
                if density.get("audit_ran") is False:
                    error_reasons.append("output density audit did not run")
                if density_errors:
                    error_reasons.extend(str(e)[:160] for e in density_errors[:3])
                if health and health.get("clean") is False:
                    issue_counts = (health.get("summary") or {}).get("issues", {})
                    error_reasons.append(f"knowledge health not clean: {issue_counts}")
                if coordinate_output_eval.get("active") and coordinate_output_eval.get("missing_count", 0):
                    error_reasons.append(
                        f"coordinate output grounding gaps: {coordinate_output_eval.get('missing_count')}"
                    )
                if data.get("validators", {}).get("father_paused"):
                    error_reasons.append("father paused by validator")

                snippet = {
                    "episode_id": data.get("episode_id") or ep_path.stem,
                    "source_file": str(ep_path.relative_to(DATA_DIR)).replace("\\", "/"),
                    "input": inp,
                    "mode": mode,
                    "knowledge_clean": health.get("clean") if health else None,
                    "knowledge_trace_count": len(trace) if isinstance(trace, list) else 0,
                    "coordinate_output_eval_active": bool(coordinate_output_eval.get("active")),
                    "coordinate_output_eval_score": coordinate_output_eval.get("score"),
                    "coordinate_output_eval_missing_count": coordinate_output_eval.get("missing_count", 0),
                    "coordinate_eval_active": bool(coordinate_output_eval.get("active")),
                    "coordinate_eval_score": coordinate_output_eval.get("score"),
                    "coordinate_eval_missing_count": coordinate_output_eval.get("missing_count", 0),
                    "density": density.get("density"),
                    "council_verdict": council.get("verdict"),
                    "has_error": bool(error_reasons),
                    "error_reasons": error_reasons[:5],
                }
                snippets.append(snippet)
                for reason in error_reasons[:3]:
                    errors.append({"input": inp[:120], "error": reason, "episode_id": snippet["episode_id"]})
            except Exception:
                pass

    # Backward-compatible fallback for pre-harness JSON session stores.
    if not snippets:
        for sessions_dir, pattern in (
            (DATA_DIR / "conversation_history", "**/*.json"),
            (DATA_DIR / "sessions", "*.json"),
        ):
            if not sessions_dir.exists():
                continue
            source = str(sessions_dir.relative_to(DATA_DIR)).replace("\\", "/")
            files = sorted(sessions_dir.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
            for sf in files[:max_n]:
                try:
                    data = json.loads(sf.read_text(encoding="utf-8"))
                    inp = str(data.get("input", ""))[:200]
                    err = str(data.get("error") or "")
                    mode = data.get("pipeline_mode", "")
                    snippets.append({"input": inp, "mode": mode, "has_error": bool(err), "source_file": str(sf)})
                    if err:
                        errors.append({"input": inp[:100], "error": err[:200]})
                except Exception:
                    pass
            if snippets:
                break

    return {"analyzed": len(snippets), "source": source, "errors_found": len(errors),
            "error_samples": errors[:5], "snippets": snippets}


def step_scan_upgrade_log() -> Dict:
    """讀取升級日誌，了解歷史。"""
    entries = []
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text(encoding="utf-8").strip().splitlines()[-20:]:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    installed = [e.get("tool_name", "") for e in entries]
    return {"count": len(entries), "installed_tools": installed}


def step_identify_gaps(
    tool_scan: Dict,
    session_scan: Dict,
    log_scan: Dict,
    perf_gaps: Optional[List[Dict]] = None,
    vessel_scan: Optional[Dict] = None,
) -> List[Dict]:
    """
    基於掃描結果，用規則識別明顯缺口。
    Priority order: density_gaps (§4.6) > perf_gaps > purpose_gaps > hardware_gaps > inventory gaps.
    返回缺口列表供 Claude 設計工具。
    """
    # Layer 3: density-signal gaps — highest priority (protocol failures)
    try:
        density_gaps = density_gaps_for_upgrade()
    except Exception:
        density_gaps = []

    # Layer 4: purpose gaps — capabilities required by system purpose but missing from TOOL_REGISTRY
    try:
        from services.system_identity import get_identity
        identity = get_identity()
        purpose_gaps = []
        for cap in identity.missing_capabilities():  # score < 0.3
            purpose_gaps.append({
                "id":          f"purpose_{cap.capability_id}",
                "type":        "purpose_gap",
                "priority":    "high",
                "description": (
                    f"核心能力缺口：[{cap.capability_id}] {cap.description} "
                    f"（覆蓋率 {cap.coverage_score:.0%}）。"
                    f"系統目的要求此能力但 TOOL_REGISTRY 冇對應工具。"
                ),
                "evidence":    f"keywords expected: {', '.join(cap.required_keywords)}; found tools: {cap.installed_tools or ['none']}",
                "capability":  cap.capability_id,
            })
        for cap in identity.weak_capabilities():  # score 0.3-0.7
            purpose_gaps.append({
                "id":          f"purpose_weak_{cap.capability_id}",
                "type":        "purpose_gap",
                "priority":    "medium",
                "description": (
                    f"核心能力薄弱：[{cap.capability_id}] {cap.description} "
                    f"（覆蓋率僅 {cap.coverage_score:.0%}）。"
                ),
                "evidence":    f"partial tools: {cap.installed_tools}",
                "capability":  cap.capability_id,
            })
    except Exception:
        purpose_gaps = []

    tools = set(tool_scan.get("tools", []))
    by_cat = tool_scan.get("by_category", {})
    errors = session_scan.get("error_samples", [])
    gaps = []
    hardware_gaps: List[Dict] = []

    if vessel_scan:
        try:
            from services.vessel_scanner import identify_hardware_tool_gaps

            hardware_gaps = identify_hardware_tool_gaps(vessel_scan, tools)
        except Exception as exc:
            hardware_gaps = [{
                "id": "hardware_gap_scan_error",
                "type": "hardware_gap_error",
                "category": "hardware",
                "description": "Vessel hardware gap scan failed.",
                "evidence": f"{type(exc).__name__}: {exc}",
                "priority": "medium",
            }]

    # 規則 1：類別嚴重不足（少於 2 個工具）
    for cat, cat_tools in by_cat.items():
        if len(cat_tools) < 2 and cat not in ("wait",):
            gaps.append({
                "id": f"gap_cat_{cat}",
                "type": "category_gap",
                "category": cat,
                "evidence": f"類別 '{cat}' 只有 {len(cat_tools)} 個工具",
                "priority": "medium",
            })

    # 規則 2：常見缺失工具
    EXPECTED = [
        ("send_notification",  "misc",     "發送 Windows toast 通知",     "用戶任務完成後無法主動通知"),
        ("wait_for_window",    "nav",      "等待特定視窗出現（有 timeout）", "現有 wait 係盲等，唔識等視窗"),
        ("ocr_read_screen",    "screen",   "OCR 識別屏幕文字",             "read_screen_text 靠 UIA，遊戲/圖像 UI 唔支援"),
        ("read_excel",         "file",     "讀取 Excel 文件返回 JSON",     "extract_document 唔支援 xlsx"),
        ("watch_file",         "file",     "監視文件/目錄變化",            "冇文件監控能力"),
        ("play_sound",         "misc",     "播放系統提示音或音效文件",      "冇音頻反饋工具"),
        ("image_match_click",  "mouse",    "圖像模板匹配點擊",             "find_and_click 依賴 vision model，圖像匹配更快更準"),
    ]
    for tool_name, cat, desc, reason in EXPECTED:
        if tool_name not in tools:
            gaps.append({
                "id": f"gap_missing_{tool_name}",
                "type": "missing_tool",
                "suggested_name": tool_name,
                "category": cat,
                "description": desc,
                "evidence": reason,
                "priority": "high" if cat in ("screen", "file", "nav") else "medium",
            })

    # 規則 3：從錯誤記錄識別
    for err in errors:
        inp = err.get("input", "").lower()
        er  = err.get("error", "").lower()
        if "excel" in inp or "xlsx" in inp:
            if "read_excel" not in tools:
                gaps.append({"id": "gap_excel_error", "type": "error_pattern",
                             "evidence": f"用戶嘗試 Excel 操作但失敗：{err.get('input','')[:100]}",
                             "category": "file", "priority": "high"})
        if "notif" in inp or "通知" in inp or "alert" in inp:
            gaps.append({"id": "gap_notif_error", "type": "error_pattern",
                         "evidence": f"用戶嘗試通知操作：{err.get('input','')[:100]}",
                         "category": "misc", "priority": "medium"})

    # Merge: density (§4.6) > performance > purpose > hardware > inventory
    all_gaps = density_gaps + list(perf_gaps or []) + purpose_gaps + hardware_gaps + gaps

    # Dedup (keep first occurrence)
    seen: set = set()
    unique = []
    for g in all_gaps:
        gid = g.get("id") or g.get("gap_id", "")
        if gid not in seen:
            seen.add(gid)
            unique.append(g)

    # Sort: density critical → performance → purpose → hardware → high → medium
    _type_order = {"density_gap": 0, "performance": 1, "purpose_gap": 2, "hardware": 3}
    _prio_order = {"critical": 0, "high": 1, "medium": 2}

    def _sort_key(g: Dict) -> tuple:
        return (
            _type_order.get(g.get("type", ""), 4),
            _prio_order.get(g.get("priority", "medium"), 2),
        )

    return sorted(unique, key=_sort_key)


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _literal_string(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def assess_tool_risk(spec: Dict) -> Dict:
    """Classify generated tool code before auto-install."""
    code = spec.get("python_code", "") or ""
    blocked: List[str] = []
    review: List[str] = []

    blocked_calls = {"eval", "exec", "__import__"}
    review_imports = {
        "subprocess",
        "socket",
        "requests",
        "httpx",
        "urllib",
        "ftplib",
        "paramiko",
    }
    review_calls = {
        "os.system",
        "os.popen",
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "shutil.rmtree",
        "Path.write_text",
        "Path.write_bytes",
        "Path.unlink",
    }
    core_files = {"app.py", "trinity_console.py", "planner_executor.py", "computer_tools.py"}

    for marker in core_files:
        if marker in code:
            review.append(f"references URUK core file: {marker}")

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"level": "failed", "reasons": [f"syntax_error: {e}"]}

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            call = _call_name(node.func)
            if call in blocked_calls:
                blocked.append(f"blocked dynamic code call: {call}")
            if (
                call in review_calls
                or call.startswith(("requests.", "httpx.", "socket."))
                or call.endswith((".write_text", ".write_bytes", ".unlink", ".remove", ".rmdir"))
            ):
                review.append(f"requires review for high-impact call: {call}")
            if call == "open":
                mode = _literal_string(node.args[1]) if len(node.args) >= 2 else ""
                for kw in node.keywords:
                    if kw.arg == "mode":
                        mode = _literal_string(kw.value)
                if any(flag in mode for flag in ("w", "a", "x", "+")):
                    review.append("requires review for file write via open()")
        elif isinstance(node, ast.Attribute):
            attr = _call_name(node)
            if attr == "os.environ":
                review.append("requires review for environment variable access")

    for module in sorted(imports & review_imports):
        review.append(f"requires review for import: {module}")

    if blocked:
        return {"level": "blocked", "reasons": sorted(set(blocked))}
    if review:
        return {"level": "needs_review", "reasons": sorted(set(review))}
    return {"level": "safe", "reasons": []}


def step_validate_tool_specs(specs: List[Dict]) -> Dict:
    """
    驗證 Claude 返回的工具 spec 列表。
    每個 spec 必須有：name, description, category, python_code (含 execute 函數)。
    返回通過 + 失敗嘅分類。
    """
    from services.computer_tools import TOOL_REGISTRY
    existing = set(TOOL_REGISTRY.keys())

    passed = []
    failed = []
    needs_review = []

    for spec in specs:
        name = spec.get("name", "")
        code = spec.get("python_code", "")
        reasons = []

        # 名稱檢查
        if not name or not re.match(r'^[a-z][a-z0-9_]*$', name):
            reasons.append(f"工具名稱不合法: '{name}'")
        if name in existing:
            reasons.append(f"與現有工具衝突: '{name}'")

        # 語法檢查
        tree = None
        try:
            tree = ast.parse(code)
            fn_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
            if "execute" not in fn_names:
                reasons.append("缺少 execute() 函數")
        except SyntaxError as e:
            reasons.append(f"語法錯誤 line {e.lineno}: {e.msg}")

        if tree is not None:
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".", 1)[0])
            for module in sorted(imports):
                if module in getattr(sys, "stdlib_module_names", set()):
                    continue
                if importlib.util.find_spec(module) is None:
                    reasons.append(f"缺少依賴: import {module}")

        risk = assess_tool_risk(spec)
        if risk["level"] == "blocked":
            reasons.extend(risk["reasons"])

        try:
            compile(_render_custom_tool_module(spec, "validation"), f"<custom_tool:{name}>", "exec")
        except SyntaxError as e:
            reasons.append(f"工具包裝語法錯誤 line {e.lineno}: {e.msg}")
        except Exception as e:
            reasons.append(f"工具包裝生成失敗: {type(e).__name__}: {e}")

        if reasons:
            failed.append({"spec": spec, "reasons": reasons})
        elif risk["level"] == "needs_review":
            needs_review.append({"spec": spec, "reasons": risk["reasons"], "risk": risk})
        else:
            passed.append(spec)

    return {
        "passed": passed,
        "failed": failed,
        "needs_review": needs_review,
        "pass_count": len(passed),
        "fail_count": len(failed),
        "review_count": len(needs_review),
    }


def _render_custom_tool_module(spec: Dict, installed_at: str) -> str:
    name = spec["name"]
    desc = spec.get("description", "")
    category = spec.get("category", "misc")
    args = spec.get("args", [])
    code = spec["python_code"]

    args_repr = repr(args)
    return "\n".join([
        f'"""',
        f'URUK auto-upgraded tool: {name}',
        f'Installed: {installed_at}',
        f'"""',
        "from services.computer_tools import ToolSpec, ArgSpec",
        "",
        "SPEC = ToolSpec(",
        f"    name={repr(name)},",
        f"    description={repr(desc)},",
        f"    args=[ArgSpec(**a) for a in {args_repr}],",
        "    needs_visual=False,",
        f"    category={repr(category)},",
        ")",
        "",
        code,
        "",
    ])


def step_install_tools(validated_specs: List[Dict]) -> List[str]:
    """安裝通過驗證嘅工具到 custom_tools/。"""
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    init = CUSTOM_DIR / "__init__.py"
    if not init.exists():
        init.write_text("# URUK custom tools\n", encoding="utf-8")

    installed = []
    now = datetime.now().isoformat()

    for spec in validated_specs:
        name = spec["name"]
        module_src = _render_custom_tool_module(spec, now)
        path = CUSTOM_DIR / f"{name}.py"
        path.write_text(module_src, encoding="utf-8")
        installed.append(name)

    return installed


def step_pre_install_snapshot(plan: "UpgradePlan") -> Dict:
    """Create a checksum manifest before installing generated tools."""
    from services.upgrade_snapshot import create_upgrade_snapshot

    snapshot = create_upgrade_snapshot(
        plan_id=plan.plan_id,
        label="pre_install",
        root=APP_ROOT,
        output_dir=DATA_DIR / "upgrade_snapshots",
        extra_paths=[CUSTOM_DIR],
    )
    plan.snapshots["pre_install"] = {
        "path": snapshot.get("path"),
        "aggregate_sha256": snapshot.get("aggregate_sha256"),
        "file_count": snapshot.get("file_count"),
        "missing_count": snapshot.get("missing_count"),
        "created_at": snapshot.get("created_at"),
    }
    plan.save()
    return plan.snapshots["pre_install"]


def step_hot_reload() -> Dict:
    """觸發 URUK 熱載入。"""
    from services.computer_tools import _load_custom_tools, TOOL_REGISTRY
    loaded = _load_custom_tools()
    refresh_identity()  # rebuild capability coverage after new tools are in registry
    return {"reloaded": loaded, "total_tools": len(TOOL_REGISTRY)}


def _write_smoke_xlsx(path: Path) -> None:
    """Create a tiny valid .xlsx workbook for read_excel smoke tests."""
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        "xl/worksheets/sheet1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>name</t></is></c><c r="B1" t="inlineStr"><is><t>value</t></is></c></row>
    <row r="2"><c r="A2" t="inlineStr"><is><t>smoke</t></is></c><c r="B2"><v>1</v></c></row>
  </sheetData>
</worksheet>""",
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def _smoke_args_for_tool(tool_name: str) -> Dict:
    from services.computer_tools import TOOL_REGISTRY

    spec = TOOL_REGISTRY.get(tool_name)
    args: Dict[str, Any] = {}
    if tool_name == "read_excel":
        sample = DATA_DIR / "tmp" / "smoke_read_excel.xlsx"
        _write_smoke_xlsx(sample)
        args["path"] = str(sample)
        args["max_rows"] = 5
        args["max_cols"] = 5
        args["header_row"] = 1
    if tool_name == "wait_for_window":
        args["title"] = "URUK_SMOKE_TEST_NO_SUCH_WINDOW"
        args["timeout"] = 0.01
        args["timeout_seconds"] = 0.01
        args["poll_interval"] = 0.01

    if not spec:
        return args
    for arg in spec.args:
        if arg.name in args:
            continue
        if not arg.required:
            continue
        if arg.type == "str":
            args[arg.name] = "smoke"
        elif arg.type == "int":
            args[arg.name] = 1
        elif arg.type == "float":
            args[arg.name] = 0.01
        elif arg.type == "bool":
            args[arg.name] = False
    return args


def step_smoke_test(tool_names: List[str]) -> Dict:
    """
    對新安裝嘅工具做基本 smoke test。
    只測試呼叫唔會 crash（唔驗證業務邏輯）。
    """
    from services.computer_tools import execute_tool
    results = {}
    for name in tool_names:
        try:
            args = _smoke_args_for_tool(name)
            result = execute_tool(name, args)
            output_has_error = isinstance(result.output, dict) and bool(result.output.get("error"))
            results[name] = {
                "ok": bool(result.ok and not output_has_error),
                "args": args,
                "has_error": bool(result.error) or output_has_error,
                "error": result.error or (result.output.get("error") if isinstance(result.output, dict) else ""),
                "output": result.output,
            }
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)[:100]}
    passed = [n for n, r in results.items() if r.get("ok")]
    failed = [n for n, r in results.items() if not r.get("ok")]
    return {"results": results, "passed": passed, "failed": failed}


def performance_gap_scan() -> List[Dict]:
    """Read latest benchmark scores and return structured performance gaps."""
    if not BASELINES_PATH.exists():
        return []
    try:
        data = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

    latest = data.get("latest")
    baseline = data.get("baseline")
    if not latest:
        return []

    gaps: List[Dict] = []
    THRESHOLD = 0.7

    # Overall IoU regression vs baseline
    if baseline:
        b_iou = baseline.get("framing_iou", 0.0)
        l_iou = latest.get("framing_iou", 0.0)
        if b_iou - l_iou > 0.05:
            gaps.append({
                "id": "perf_overall_iou_regression",
                "type": "performance",
                "category": "performance",
                "priority": "high",
                "description": (
                    f"Overall framing IoU dropped {b_iou - l_iou:.3f} "
                    f"from baseline {b_iou:.3f} to {l_iou:.3f}"
                ),
                "evidence": {"baseline_iou": b_iou, "latest_iou": l_iou, "delta": l_iou - b_iou},
            })

    # Per-task low performers — skip domains that already have a tool installed.
    # Cross-reference against the upgrade log so repeated audits don't keep
    # proposing the same tool names (which the LLM may ignore even when banned).
    _installed_from_log: List[str] = []
    if LOG_PATH.exists():
        try:
            for _line in LOG_PATH.read_text(encoding="utf-8").strip().splitlines()[-30:]:
                _entry = json.loads(_line)
                _tname = _entry.get("tool_name", "")
                if _tname:
                    _installed_from_log.append(_tname.lower())
        except Exception:
            pass

    per_task_iou = latest.get("per_task_iou", {})
    _window_label = {
        "A": "historical_wwi", "B": "historical_wwii",
        "C": "historical_coldwar", "D": "modern_2024", "N": "negative_control",
    }
    # Domain keyword fragments — if any installed tool name contains one of these,
    # skip all gaps in that window (the domain has already been addressed).
    _window_keywords = {
        "historical_wwi":    ["wwi", "worldwar1", "world_war_1", "ww1"],
        "historical_wwii":   ["wwii", "worldwar2", "world_war_2", "ww2"],
        "historical_coldwar":["coldwar", "cold_war"],
        "modern_2024":       ["modern_2024", "modern2024"],
        "negative_control":  ["negative_control"],
    }
    _addressed_windows: set = set()
    for _tname in _installed_from_log:
        for _window, _keywords in _window_keywords.items():
            if any(_kw in _tname for _kw in _keywords):
                _addressed_windows.add(_window)

    for tid, score in per_task_iou.items():
        if score < THRESHOLD:
            cat = _window_label.get(tid[0], "unknown")
            if cat in _addressed_windows:
                continue  # domain already addressed — skip to avoid duplicate proposals
            gaps.append({
                "id": f"perf_framing_task_{tid.replace('-', '_').lower()}",
                "type": "performance",
                "category": "performance",
                "priority": "high" if score < 0.5 else "medium",
                "description": (
                    f"Trinity scores {score:.2f} on task {tid} ({cat}) "
                    f"below threshold {THRESHOLD}"
                ),
                "evidence": {"task_id": tid, "score": score, "threshold": THRESHOLD, "category": cat},
            })

    return gaps


def step_rollback(plan: "UpgradePlan", tools_to_remove: List[str]) -> Dict:
    """Delete freshly installed tool files and hot-reload the registry."""
    removed = []
    for name in tools_to_remove:
        path = CUSTOM_DIR / f"{name}.py"
        if path.exists():
            path.unlink()
            removed.append(name)
    try:
        from services.computer_tools import _load_custom_tools
        _load_custom_tools()
    except Exception:
        pass
    result: Dict[str, Any] = {"removed": removed, "requested": tools_to_remove}
    snapshot_ref = (plan.snapshots or {}).get("pre_install") or {}
    snapshot_path = snapshot_ref.get("path")
    if snapshot_path:
        try:
            from services.upgrade_snapshot import diff_upgrade_snapshot, load_upgrade_snapshot

            snapshot = load_upgrade_snapshot(snapshot_path)
            result["snapshot_diff"] = diff_upgrade_snapshot(snapshot)
        except Exception as exc:
            result["snapshot_diff_error"] = f"{type(exc).__name__}: {exc}"
    return result


def knowledge_audit_gate() -> Dict:
    """Run the knowledge corpus audit as a lightweight upgrade gate."""
    try:
        report = audit_knowledge(root=APP_ROOT)
    except Exception as e:
        return {
            "passed": False,
            "error": f"{type(e).__name__}: {e}",
            "fatal_issues": [{"severity": "P0", "code": "knowledge_audit_error"}],
        }
    fatal = [issue for issue in report.get("issues", []) if issue.get("severity") == "P0"]
    return {
        "passed": not fatal,
        "summary": report.get("summary", {}),
        "rag": report.get("rag", {}),
        "fatal_issues": fatal,
    }


def benchmark_gate(cases_path: Optional[Path] = None) -> Dict:
    """Run the built-in deterministic coordinate benchmark as an upgrade gate."""
    try:
        from tools.benchmark_runner import DEFAULT_CASES, run_cases

        path = Path(cases_path) if cases_path else DEFAULT_CASES
        report = run_cases(path, root=APP_ROOT)
    except Exception as e:
        return {
            "passed": False,
            "error": f"{type(e).__name__}: {e}",
            "failed_cases": ["benchmark_runner_error"],
        }

    failed = [item for item in report.get("results", []) if not item.get("passed")]
    return {
        "passed": bool(report.get("passed")),
        "suite_id": report.get("suite_id"),
        "case_count": report.get("case_count", 0),
        "passed_count": report.get("passed_count", 0),
        "failed_count": report.get("failed_count", 0),
        "failed_cases": [item.get("id") for item in failed],
        "path": str((Path(cases_path) if cases_path else DEFAULT_CASES).resolve()),
    }


def stability_golden_gate(cases_path: Optional[Path] = None) -> Dict:
    """Run deterministic runtime contract golden cases as an upgrade gate."""
    try:
        from services.stability_golden import DEFAULT_CASES, run_golden_cases

        path = Path(cases_path) if cases_path else DEFAULT_CASES
        report = run_golden_cases(path, root=APP_ROOT)
    except Exception as e:
        return {
            "passed": False,
            "error": f"{type(e).__name__}: {e}",
            "failed_cases": ["stability_golden_error"],
        }

    failed = [item for item in report.get("results", []) if not item.get("passed")]
    return {
        "passed": bool(report.get("passed")),
        "suite_id": report.get("suite_id"),
        "case_count": report.get("case_count", 0),
        "passed_count": report.get("passed_count", 0),
        "failed_count": report.get("failed_count", 0),
        "failed_cases": [item.get("id") for item in failed],
        "path": str((Path(cases_path) if cases_path else DEFAULT_CASES).resolve()),
    }


def quick_eval_gate() -> Dict:
    """Run external quick_eval if available; skipped quick_eval is not a hard failure."""
    benchmark_dir = APP_ROOT / "external" / "uruk-benchmark"
    quick_eval_path = benchmark_dir / "quick_eval.py"
    if not quick_eval_path.exists():
        return {
            "available": False,
            "skipped": True,
            "passed": None,
            "reason": "quick_eval.py not found",
            "path": str(quick_eval_path.resolve()),
        }

    baseline_iou: Optional[float] = None
    baseline_chain: Optional[float] = None
    if BASELINES_PATH.exists():
        try:
            bl_data = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
            bl = bl_data.get("baseline") or bl_data.get("latest")
            if bl:
                baseline_iou = bl.get("framing_iou")
                baseline_chain = bl.get("chain_match")
        except Exception as e:
            return {
                "available": True,
                "skipped": True,
                "passed": None,
                "reason": f"baseline unreadable: {type(e).__name__}: {e}",
                "path": str(quick_eval_path.resolve()),
            }

    if baseline_iou is None:
        return {
            "available": True,
            "skipped": True,
            "passed": None,
            "reason": "no baseline; run quick_eval --baseline first",
            "path": str(quick_eval_path.resolve()),
        }

    try:
        import asyncio as _asyncio
        import concurrent.futures as _futures
        import sys as _sys
        if str(benchmark_dir) not in _sys.path:
            _sys.path.insert(0, str(benchmark_dir))
        from quick_eval import quick_eval as _quick_eval  # type: ignore
        # asyncio.run() fails when called from inside a running event loop (FastAPI).
        # Run the coroutine in a dedicated thread so it gets its own event loop.
        try:
            _asyncio.get_running_loop()
            _in_async = True
        except RuntimeError:
            _in_async = False
        if _in_async:
            with _futures.ThreadPoolExecutor(max_workers=1) as _pool:
                scores = _pool.submit(_asyncio.run, _quick_eval()).result(timeout=60)
        else:
            scores = _asyncio.run(_quick_eval())
    except Exception as e:
        return {
            "available": True,
            "skipped": True,
            "passed": None,
            "reason": f"quick_eval failed: {type(e).__name__}: {e}",
            "path": str(quick_eval_path.resolve()),
        }

    regression_threshold = 0.05
    delta_iou = round(scores["framing_iou"] - baseline_iou, 4)
    delta_chain = round(scores["chain_match"] - (baseline_chain or 0.0), 4)
    regressed = delta_iou < -regression_threshold or delta_chain < -regression_threshold
    return {
        "available": True,
        "skipped": False,
        "passed": not regressed,
        "regressed": regressed,
        "framing_iou": scores["framing_iou"],
        "chain_match": scores["chain_match"],
        "baseline_framing_iou": baseline_iou,
        "baseline_chain_match": baseline_chain,
        "framing_iou_delta": delta_iou,
        "chain_match_delta": delta_chain,
        "timestamp": scores.get("timestamp"),
        "scores": scores,
        "path": str(quick_eval_path.resolve()),
    }


def run_upgrade_gate_preflight() -> Dict:
    """Read-only self-upgrade gate check used by API/UI before installation."""
    knowledge_gate = knowledge_audit_gate()
    coordinate_benchmark = benchmark_gate()
    stability_golden = stability_golden_gate()
    quick_eval = quick_eval_gate()
    hard_failed = (
        not knowledge_gate.get("passed")
        or not coordinate_benchmark.get("passed")
        or not stability_golden.get("passed")
        or quick_eval.get("passed") is False
    )
    return {
        "ok": not hard_failed,
        "checked_at": datetime.now().isoformat(),
        "knowledge_audit": knowledge_gate,
        "benchmark": coordinate_benchmark,
        "stability_golden": stability_golden,
        "quick_eval": quick_eval,
    }


def step_post_install_eval(plan: "UpgradePlan", installed: List[str]) -> Dict:
    """Run deterministic post-install gates and rollback on regression."""
    knowledge_gate = knowledge_audit_gate()
    if not knowledge_gate.get("passed"):
        rollback = step_rollback(plan, installed)
        plan.status = "rolled_back"
        plan.summary += (
            f" Knowledge audit failed with P0 issues; rolled back tools: "
            f"{rollback['removed']}."
        )
        plan.save()
        return {
            "regressed": True,
            "reason": "knowledge_audit_p0",
            "knowledge_audit": knowledge_gate,
            "rollback": rollback,
        }

    coordinate_benchmark = benchmark_gate()
    if not coordinate_benchmark.get("passed"):
        rollback = step_rollback(plan, installed)
        plan.status = "rolled_back"
        failed_cases = coordinate_benchmark.get("failed_cases") or []
        plan.summary += (
            f" Coordinate benchmark failed; rolled back tools: "
            f"{rollback['removed']}. Failed cases: {failed_cases}."
        )
        plan.save()
        return {
            "regressed": True,
            "reason": "coordinate_benchmark_failed",
            "knowledge_audit": knowledge_gate,
            "benchmark": coordinate_benchmark,
            "rollback": rollback,
        }

    stability_golden = stability_golden_gate()
    if not stability_golden.get("passed"):
        rollback = step_rollback(plan, installed)
        plan.status = "rolled_back"
        failed_cases = stability_golden.get("failed_cases") or []
        plan.summary += (
            f" Stability golden cases failed; rolled back tools: "
            f"{rollback['removed']}. Failed cases: {failed_cases}."
        )
        plan.save()
        return {
            "regressed": True,
            "reason": "stability_golden_failed",
            "knowledge_audit": knowledge_gate,
            "benchmark": coordinate_benchmark,
            "stability_golden": stability_golden,
            "rollback": rollback,
        }

    quick_eval = quick_eval_gate()
    if quick_eval.get("skipped"):
        return {
            "skipped": True,
            "reason": quick_eval.get("reason"),
            "regressed": False,
            "knowledge_audit": knowledge_gate,
            "benchmark": coordinate_benchmark,
            "stability_golden": stability_golden,
            "quick_eval": quick_eval,
        }

    result: Dict[str, Any] = {
        "framing_iou": quick_eval.get("framing_iou"),
        "chain_match": quick_eval.get("chain_match"),
        "baseline_framing_iou": quick_eval.get("baseline_framing_iou"),
        "baseline_chain_match": quick_eval.get("baseline_chain_match"),
        "framing_iou_delta": quick_eval.get("framing_iou_delta"),
        "chain_match_delta": quick_eval.get("chain_match_delta"),
        "regressed": bool(quick_eval.get("regressed")),
        "timestamp": quick_eval.get("timestamp"),
        "knowledge_audit": knowledge_gate,
        "benchmark": coordinate_benchmark,
        "stability_golden": stability_golden,
        "quick_eval": quick_eval,
    }

    if quick_eval.get("regressed"):
        rollback = step_rollback(plan, installed)
        result["rollback"] = rollback
        plan.status = "rolled_back"
        plan.summary += (
            f" Regression detected (framing_iou Δ={quick_eval.get('framing_iou_delta'):+.3f}); "
            f"rolled back tools: {rollback['removed']}."
        )
        plan.save()
    else:
        # Update baseline with improved/stable scores
        try:
            scores = quick_eval.get("scores") or {}
            bl_data = {}
            if BASELINES_PATH.exists():
                bl_data = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
            if not bl_data.get("baseline"):
                bl_data["baseline"] = scores
            bl_data["latest"] = scores
            bl_data.setdefault("history", []).append(scores)
            BASELINES_PATH.write_text(
                json.dumps(bl_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # Layer 2: record protocol fidelity snapshot alongside framing_iou
    try:
        fidelity_snap = record_fidelity_snapshot("latest")
        f_delta = get_fidelity_delta()
        step = plan.get_step("post_install_eval")
        if f_delta:
            plan.update_step("post_install_eval", status="done",
                             output={**(step.output or {}),
                                     "fidelity_score": fidelity_snap.fidelity_score,
                                     "fidelity_delta": f_delta})
        else:
            plan.update_step("post_install_eval", status="done",
                             output={**(step.output or {}),
                                     "fidelity_score": fidelity_snap.fidelity_score,
                                     "fidelity_sessions_analyzed": fidelity_snap.sessions_analyzed})
    except Exception as _fe:
        pass  # non-blocking

    return result


def step_write_log(plan: "UpgradePlan", installed: List[str], eval_result: Optional[Dict] = None) -> None:
    """寫入升級審計日誌。"""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        for name in installed:
            entry: Dict[str, Any] = {
                "timestamp": datetime.now().isoformat(),
                "tool_name": name,
                "plan_id": plan.plan_id,
                "mode": plan.mode,
                "installed_by": f"URUK upgrade_engine/{plan.relay_target}",
            }
            if eval_result and not eval_result.get("skipped"):
                entry["eval_delta"] = {
                    "framing_iou_delta": eval_result.get("framing_iou_delta"),
                    "chain_match_delta": eval_result.get("chain_match_delta"),
                }
            if eval_result:
                benchmark = eval_result.get("benchmark") or {}
                stability = eval_result.get("stability_golden") or {}
                snapshot = (plan.snapshots or {}).get("pre_install") or {}
                entry["regression_gate"] = {
                    "knowledge_audit_passed": (eval_result.get("knowledge_audit") or {}).get("passed"),
                    "benchmark_passed": benchmark.get("passed"),
                    "benchmark_cases": benchmark.get("case_count"),
                    "benchmark_failed_cases": benchmark.get("failed_cases"),
                    "stability_golden_passed": stability.get("passed"),
                    "stability_golden_cases": stability.get("case_count"),
                    "stability_golden_failed_cases": stability.get("failed_cases"),
                    "pre_install_snapshot": snapshot.get("path"),
                    "pre_install_snapshot_sha256": snapshot.get("aggregate_sha256"),
                }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────────
# Plan builder
# ─────────────────────────────────────────────────────────────────

def _relay_display_name(relay_target: str) -> str:
    return {
        "claude": "Claude Desktop",
        "claude_code": "Claude Code",
        "chatgpt": "ChatGPT Desktop",
        "codex": "Codex Desktop",
        "local": "local LLM",
        "cowork": "Claude Cowork",
    }.get(relay_target or "", relay_target or "relay")


def build_plan(mode: str, relay_target: str = "claude", max_sessions: int = 10) -> UpgradePlan:
    """
    執行所有 system steps（掃描 + 識別缺口），生成計劃書。
    計劃書包含 relay design step（待外部或本地模型填寫工具代碼）。
    """
    plan_id = f"upgrade-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    plan = UpgradePlan(
        plan_id=plan_id,
        mode=mode,
        relay_target=relay_target,
        created_at=datetime.now().isoformat(),
    )

    # 定義步驟列表
    plan.execution_contract = dict(DEFAULT_EXECUTION_CONTRACT)
    plan.steps = [
        _make_step(1, "system", "scan_tools", "掃描現有工具清單同類別分佈",
                   executor_rule="只執行 scan_tools，收集現有工具 registry 摘要",
                   success_criteria="返回工具總數、工具名、類別分佈"),
        _make_step(2, "system", "scan_sessions", f"分析最近 {max_sessions} 個對話記錄",
                   executor_rule="只讀 data/harness_episodes 最近 episode；fallback 才讀舊 session JSON，不寫入",
                   success_criteria="返回 analyzed/error_samples/snippets"),
        _make_step(3, "system", "scan_upgrade_log", "讀取歷史升級日誌",
                   executor_rule="只讀 upgrade_log.jsonl 最近記錄",
                   success_criteria="返回已安裝工具清單"),
        _make_step(4, "system", "identify_gaps", "識別工具缺口同問題模式",
                   executor_rule="用 scan 結果識別工具缺口，不產生代碼",
                   success_criteria="返回排序後 gaps"),
        PlanStep(5, relay_target, "design_tools", description="大模型根據缺口設計新工具代碼同執行規則"),
        _make_step(6, "system", "validate_code", "AST 語法 + 安全掃描驗證代碼",
                   executor_rule="細模型只可確認 validate_code；若發現高風險代碼特徵則 requires_human",
                   success_criteria="至少一個 tool spec 通過語法與安全驗證"),
        _make_step(7, "system", "pre_install_snapshot", "Create checksum manifest before installing generated tools",
                   executor_rule="Read-only snapshot of core runtime, config, benchmark, frontend, and custom tool files",
                   success_criteria="Snapshot manifest written under data/upgrade_snapshots with aggregate checksum"),
        _make_step(7, "system", "install_tools", "安裝通過驗證嘅工具到 custom_tools/",
                   executor_rule="只可安裝 validation passed specs；不可安裝 failed specs",
                   success_criteria="custom_tools 產生對應 Python module"),
        _make_step(8, "system", "hot_reload", "觸發熱載入，新工具即時生效",
                   executor_rule="只可呼叫 hot_reload 重新載入 custom_tools",
                   success_criteria="TOOL_REGISTRY 包含新工具"),
        _make_step(9, "system", "smoke_test", "對新工具做基本 smoke test",
                   executor_rule="只對剛安裝工具做空 args smoke test",
                   success_criteria="返回 passed/failed 清單"),
        _make_step(10, "system", "post_install_eval",
                   "運行 knowledge audit、coordinate benchmark、quick_eval；regression 則自動回滾",
                   executor_rule="先跑內建 deterministic gates，再執行 quick_eval subset；如任一硬閘失敗或 regression > 0.05 觸發回滾",
                   success_criteria="knowledge audit clean、coordinate benchmark pass、framing_iou_delta >= -0.05 且 chain_match_delta >= -0.05"),
        _make_step(11, "system", "write_log", "寫入審計日誌（含 eval_delta）",
                   executor_rule="只寫入已安裝工具嘅審計記錄",
                   success_criteria="upgrade_log.jsonl 有對應 plan_id 記錄"),
    ]
    plan.steps.insert(
        1,
        _make_step(
            2,
            "system",
            "scan_vessel",
            "Scan runtime vessel hardware and capability profile",
            executor_rule="Read-only hardware scan; no actuator control and no generated code",
            success_criteria="Return VesselProfile with capabilities and tool expectations",
        ),
    )
    for idx, step in enumerate(plan.steps, 1):
        step.id = idx

    plan.status = "running"
    plan.save()

    t0 = time.time()

    # Step 1: scan tools
    plan.update_step("scan_tools", "running")
    tool_scan = step_scan_tools()
    plan.update_step("scan_tools", "done", output=tool_scan,)

    # Step 2: scan vessel hardware
    plan.update_step("scan_vessel", "running")
    vessel_scan = step_scan_vessel()
    plan.update_step("scan_vessel", "done", output=vessel_scan)

    # Step 3: scan sessions
    plan.update_step("scan_sessions", "running")
    session_scan = step_scan_sessions(max_sessions)
    plan.update_step("scan_sessions", "done", output=session_scan)

    # Step 4: scan log
    plan.update_step("scan_upgrade_log", "running")
    log_scan = step_scan_upgrade_log()
    plan.update_step("scan_upgrade_log", "done", output=log_scan)

    # Step 5: identify gaps (merge performance, hardware, and inventory gaps)
    plan.update_step("identify_gaps", "running")
    perf_gaps = performance_gap_scan()
    gaps = step_identify_gaps(tool_scan, session_scan, log_scan, perf_gaps, vessel_scan)
    plan.gaps = gaps
    hardware_gap_count = len([g for g in gaps if g.get("type") == "hardware_gap"])
    plan.update_step("identify_gaps", "done", output={
        "count": len(gaps),
        "gaps": gaps,
        "perf_gap_count": len(perf_gaps),
        "hardware_gap_count": hardware_gap_count,
    })

    # Layer 5: pre-upgrade self-audit — Spirit checks the upgrade plan for hidden assumptions.
    # build_plan() is sync; run_upgrade_self_audit is async → ThreadPoolExecutor bridge.
    self_audit: Optional[SelfAuditResult] = None
    try:
        import asyncio as _asyncio
        import concurrent.futures as _futures
        try:
            _asyncio.get_running_loop()
            _in_async = True
        except RuntimeError:
            _in_async = False
        try:
            _id_block = get_identity().to_prompt_block()
        except Exception:
            _id_block = ""
        _top_gaps = gaps[:5]
        if _in_async:
            # Called from FastAPI — can't use asyncio.run(); spawn dedicated thread
            with _futures.ThreadPoolExecutor(max_workers=1) as _pool:
                self_audit = _pool.submit(
                    _asyncio.run, run_upgrade_self_audit(_top_gaps, _id_block, plan.relay_target)
                ).result(timeout=30)
        else:
            self_audit = _asyncio.run(run_upgrade_self_audit(_top_gaps, _id_block, plan.relay_target))
        # Merge audit result into identify_gaps step output
        _ig_step = plan.get_step("identify_gaps")
        plan.update_step("identify_gaps", status=_ig_step.status,
                         output={**(_ig_step.output or {}), "self_audit": self_audit.to_dict()})
        # Spirit interrupt — operator must review before install proceeds
        if self_audit.interrupt_triggered and self_audit.recommendation == "pause":
            plan.status = "review_required"
            plan.summary = (
                f"掃描完成：{tool_scan['count']} 個工具，"
                f"分析 {session_scan['analyzed']} 個 session，"
                f"識別 {len(gaps)} 個缺口。"
                f"Spirit interrupt: {self_audit.interrupt_reason}"
            )
            plan.save()
            return plan
    except Exception:
        self_audit = None

    # Step 6 input: build prompt for Claude
    claude_input = _build_claude_design_prompt(plan, tool_scan, gaps, log_scan, self_audit)
    plan.update_step("design_tools", "pending", input=claude_input)

    relay_label = _relay_display_name(plan.relay_target)
    plan.status = "waiting_relay"
    plan.summary = (
        f"掃描完成：{tool_scan['count']} 個工具，"
        f"分析 {session_scan['analyzed']} 個 session，"
        f"識別 {len(gaps)} 個缺口。等待 {relay_label} 設計工具代碼。"
    )
    plan.save()
    return plan


def _build_perf_context_block(plan: UpgradePlan, perf_gaps: List[Dict]) -> str:
    """Format benchmark performance context for the current relay target."""
    if not perf_gaps:
        return ""

    scores_summary = ""
    if BASELINES_PATH.exists():
        try:
            bl = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
            latest = bl.get("latest", {})
            baseline = bl.get("baseline", {})
            scores_summary = (
                f"latest framing_iou={latest.get('framing_iou', 'n/a')}, "
                f"chain_match={latest.get('chain_match', 'n/a')} "
                f"(baseline iou={baseline.get('framing_iou', 'n/a')})"
            )
        except Exception:
            pass

    if plan.relay_target == "claude_code":
        # Plain observation only — no install instruction
        lines = [f"# Benchmark observation ({scores_summary}):"]
        for g in perf_gaps[:3]:
            lines.append(f"#   {g.get('description', g.get('id', ''))}")
        return "\n".join(lines)

    if plan.relay_target == "codex":
        perf_json = json.dumps(
            {"scores": scores_summary, "gaps": perf_gaps[:5]},
            ensure_ascii=False, indent=2,
        )
        return f"<PERFORMANCE_CONTEXT>\n{perf_json}\n</PERFORMANCE_CONTEXT>"

    if plan.relay_target == "chatgpt":
        # Plain text — ChatGPT does not parse XML or Kairos blocks
        lines = [f"Benchmark performance note ({scores_summary}):"]
        for g in perf_gaps[:3]:
            lines.append(f"  - {g.get('description', g.get('id', ''))}")
        return "\n".join(lines)

    # claude / local / cowork — Kairos-style evidence block
    lines = ["[KAIROS_EVIDENCE:benchmark_performance]"]
    lines.append(f"  scores: {scores_summary}")
    for g in perf_gaps[:5]:
        lines.append(f"  gap: {g.get('description', g.get('id', ''))}")
        if g.get("evidence"):
            lines.append(f"    evidence: {json.dumps(g['evidence'], ensure_ascii=False)}")
    lines.append("[/KAIROS_EVIDENCE]")
    return "\n".join(lines)


def _build_claude_design_prompt(
    plan: UpgradePlan,
    tool_scan: Dict,
    gaps: List[Dict],
    log_scan: Optional[Dict] = None,
    self_audit: Optional["SelfAuditResult"] = None,
) -> str:
    """生成發送給 Claude 嘅設計任務 prompt。"""
    # Claude Code is slower and stricter about automated-install protocols, so
    # one reviewable candidate per cycle is the safest fit for that backend.
    top_gaps = gaps[:1] if plan.relay_target == "claude_code" else gaps[:3]
    tool_names = ", ".join(tool_scan.get("tools", []))

    # Layer 1: prepend system identity so the designer knows what capabilities
    # already exist and what the system's canonical purpose is.
    try:
        _identity_block = get_identity().to_prompt_block() + "\n\n"
    except Exception:
        _identity_block = ""

    # Layer 5: prepend self-audit result (Spirit interrupt or clear-to-proceed)
    try:
        _audit_block = (self_audit.to_prompt_block() + "\n\n") if (self_audit and self_audit.ran) else ""
    except Exception:
        _audit_block = ""

    # Build a BANNED list from the upgrade log so the LLM never re-proposes a
    # name that's already installed (even if the gap description points to the
    # same domain). The registered-tool list alone is insufficient because the
    # LLM may match by domain keyword rather than exact name.
    _recently_installed: List[str] = []
    if log_scan:
        _recently_installed = [
            t for t in (log_scan.get("installed_tools") or []) if t
        ][:20]
    _banned_block = ""
    if _recently_installed:
        _banned_block = (
            f"\nRECENTLY INSTALLED — BANNED NAMES (do not reuse, even partially):"
            f" {', '.join(_recently_installed)}\n"
        )

    perf_gaps = [g for g in gaps if g.get("type") == "performance"]
    perf_block = _build_perf_context_block(plan, perf_gaps)

    gaps_text = ""
    for i, g in enumerate(top_gaps, 1):
        gaps_text += f"\n缺口 {i}：{g.get('description', g.get('id', ''))}\n"
        gaps_text += f"  類別：{g.get('category', 'misc')}\n"
        gaps_text += f"  依據：{g.get('evidence', '')}\n"
        gaps_text += f"  優先：{g.get('priority', 'medium')}\n"
        if g.get("suggested_name"):
            gaps_text += f"  建議名稱：{g['suggested_name']}\n"
        if g.get("type") == "hardware_gap":
            gaps_text += f"  hardware_capability: {g.get('hardware_capability', '')}\n"
            gaps_text += f"  accepted_tools: {', '.join(g.get('accepted_tools') or [])}\n"
            gaps_text += f"  commissioning_required: {bool(g.get('commissioning_required'))}\n"
        if g.get("type") == "purpose_gap":
            gaps_text += f"  GAP TYPE: purpose_gap (core capability missing for system purpose)\n"
            gaps_text += f"  CAPABILITY: {g.get('capability', '')}\n"
            gaps_text += f"  SYSTEM PURPOSE: 讓AI成為幫助個體找到(0,0,0)的工具\n"
            gaps_text += f"  What to design: a tool that enables agentic support for '{g.get('description', '')}'\n"
            gaps_text += f"  Evidence: {g.get('evidence', '')}\n"

    if plan.relay_target == "claude_code":
        compact_gaps = []
        for g in top_gaps:
            compact_gaps.append({
                "id": g.get("id"),
                "type": g.get("type"),
                "category": g.get("category", "misc"),
                "capability": g.get("capability") or g.get("hardware_capability"),
                "suggested_name": g.get("suggested_name"),
                "description": g.get("description"),
                "evidence": g.get("evidence"),
                "priority": g.get("priority", "medium"),
                "accepted_tools": g.get("accepted_tools") or [],
                "commissioning_required": bool(g.get("commissioning_required")),
            })
        gaps_json = json.dumps(compact_gaps, ensure_ascii=False, indent=2)
        perf_note = f"\n{perf_block}\n" if perf_block else ""
        return f"""You are helping a human developer review a local Python app at C:\\uruk-trinity-console.
The user clicked a UI self-upgrade audit button. Do not modify files, run shell commands, install packages, or execute generated code.
Draft {len(top_gaps)} safe, reviewable candidate tool(s). Keep the answer short and return only the requested tool spec block.

[UPGRADE_PLAN:{plan.plan_id}]
Plan id: {plan.plan_id}
Mode: {plan.mode}
Existing tools ({tool_scan.get('count')} total, do not duplicate exact names): {tool_names}
{_banned_block}{perf_note}
Gap context:
{gaps_json}

Use this exact plain text block format for each candidate. Replace placeholders with real values.
No markdown fences. Brief review notes are allowed after the block(s), but the block(s) must be present.

{tool_spec_block(plan.plan_id)}

Rules:
- Output exactly {len(top_gaps)} [TOOL_SPEC:{plan.plan_id}] block(s), unless the candidate is unsafe or duplicated.
- Keep the whole response under 140 lines.
- Each python_code must define execute(args: dict) -> dict and return JSON-serializable dicts.
- Do not import ToolSpec or ArgSpec in python_code.
- Keep file writes, shell execution, network access, credential access, process killing, and core-file edits out of python_code.
- Prefer standard library or dependencies already used by this app.
"""

    if plan.relay_target == "chatgpt":
        # ChatGPT Desktop: plain structured prompt, no XML envelopes, no slash commands.
        # format_chatgpt_relay_message() will prepend the adapter (role instruction +
        # upgrade_output_contract with real plan_id). This body provides context only —
        # do NOT include a duplicate role instruction or tool spec template here.
        gaps_json = json.dumps(top_gaps, ensure_ascii=False, indent=2)
        perf_note = f"\n{perf_block}\n" if perf_block else ""
        return _identity_block + _audit_block + f"""Plan ID: {plan.plan_id}
Mode: {plan.mode}
Existing tools ({tool_scan.get('count')} total, do not duplicate): {tool_names}
{_banned_block}{perf_note}
Tool gaps to fill ({len(top_gaps)} total):
{gaps_json}

Tool spec block format to use (one per gap):

{tool_spec_block(plan.plan_id)}

Rules:
- Output exactly {len(top_gaps)} [TOOL_SPEC:{plan.plan_id}] block(s).
- No markdown code fences around the blocks.
- Each python_code must define execute(args: dict) -> dict.
- Do not import ToolSpec or ArgSpec.
- No shell execution, network calls, file writes, credential access, or core-file edits.
"""

    perf_section = f"\n{perf_block}\n" if perf_block else ""
    return _identity_block + _audit_block + f"""[UPGRADE_PLAN:{plan.plan_id}]
URUK 系統已完成自動掃描，識別出以下工具缺口。
請為每個缺口設計一個 Python 工具，填入計劃書嘅 Step 5。

計劃書 ID：{plan.plan_id}
模式：{plan.mode}
現有工具（{tool_scan.get('count')} 個，唔要重複）：{tool_names}
{_banned_block}{perf_section}
=== 需要設計嘅工具（{len(top_gaps)} 個）===
{gaps_text}

{upgrade_output_contract(plan.plan_id, len(top_gaps))}

URUK 會用本地細模型逐步確認 system action，再由 upgrade_engine 自動解析、驗證、安裝你嘅設計。"""


# ─────────────────────────────────────────────────────────────────
# Plan executor (handles Claude's response)
# ─────────────────────────────────────────────────────────────────

def parse_claude_response(plan_id: str, claude_response: str) -> List[Dict]:
    """從 Claude 嘅回覆解析 [TOOL_SPEC:plan_id] 區塊。"""
    specs = []
    pattern = rf'\[TOOL_SPEC:{re.escape(plan_id)}\](.*?)(?=\[TOOL_SPEC:|$)'
    matches = re.findall(pattern, claude_response, re.DOTALL)

    for block in matches:
        spec: Dict[str, Any] = {}
        lines = block.strip().splitlines()
        current_key = None
        code_lines: List[str] = []
        in_code = False
        args_list: List[Dict] = []
        in_args = False
        current_arg: Dict = {}

        for line in lines:
            stripped = line.strip()
            if in_code:
                if stripped == "---":
                    in_code = False
                    spec["python_code"] = "\n".join(code_lines)
                else:
                    code_lines.append(line[2:] if line.startswith("  ") else line)
            elif stripped.startswith("python_code:"):
                in_args = False
                in_code = True
            elif in_args and stripped.startswith("- name:"):
                if current_arg:
                    args_list.append(current_arg)
                current_arg = {"name": stripped.split(":", 1)[1].strip(),
                               "type": "str", "required": True, "description": ""}
            elif in_args and current_arg:
                handled_arg = False
                for key in ("type", "required", "description"):
                    if stripped.startswith(f"{key}:"):
                        val = stripped.split(":", 1)[1].strip()
                        current_arg[key] = val.lower() == "true" if key == "required" else val
                        handled_arg = True
                        break
                if not handled_arg and stripped.startswith(("name:", "category:", "args:")):
                    in_args = False
            elif stripped.startswith("name:"):
                spec["name"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("description:"):
                spec["description"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("category:"):
                spec["category"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("args:"):
                in_args = True

        if current_arg:
            args_list.append(current_arg)
        if code_lines and "python_code" not in spec:
            spec["python_code"] = "\n".join(code_lines)

        spec["args"] = args_list
        if spec.get("name") and spec.get("python_code"):
            specs.append(spec)

    return specs


def apply_execution_plan_from_response(plan: UpgradePlan, response: str) -> Dict:
    """Parse optional large-model execution contract for the small executor."""
    pattern = rf'\[UPGRADE_EXECUTION_PLAN:{re.escape(plan.plan_id)}\](.*?)(?=\[TOOL_SPEC:|$)'
    match = re.search(pattern, response or "", re.DOTALL)
    if not match:
        return {"found": False, "applied_steps": 0}

    raw = match.group(1).strip()
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        return {"found": True, "applied_steps": 0, "error": "no JSON object"}

    try:
        data = json.loads(json_match.group(0))
    except Exception as e:
        return {"found": True, "applied_steps": 0, "error": f"{type(e).__name__}: {e}"}

    contract = data.get("tool_rules") if isinstance(data.get("tool_rules"), dict) else {}
    if contract:
        merged = dict(DEFAULT_EXECUTION_CONTRACT)
        merged.update(contract)
        plan.execution_contract = merged

    applied = 0
    by_action = {s.action: s for s in plan.steps}
    for step_rule in data.get("steps") or []:
        if not isinstance(step_rule, dict):
            continue
        action = str(step_rule.get("action") or "")
        step = by_action.get(action)
        if not step or step.executor != "system":
            continue
        allowed = step_rule.get("allowed_actions") or [action]
        if not isinstance(allowed, list):
            allowed = [action]
        allowed = [str(a) for a in allowed if isinstance(a, str)]
        # Each upgrade step remains narrow; the model may describe rules, not widen execution.
        step.allowed_actions = [action] if action in allowed else [action]
        step.executor_rule = str(step_rule.get("executor_rule") or step.executor_rule)
        step.success_criteria = str(step_rule.get("success_criteria") or step.success_criteria)
        applied += 1

    plan.save()
    return {"found": True, "applied_steps": applied}


def _save_relay_response(plan_id: str, response: str) -> str:
    """Persist raw relay output beside the plan for debugging and audit review."""
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    path = PLANS_DIR / f"{plan_id}.relay.txt"
    path.write_text(response or "", encoding="utf-8")
    return str(path)


def _extract_json_object(text: str) -> Optional[Dict]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _small_executor_context(context: Dict) -> Dict:
    """Keep local executor context compact to reduce local prompt size."""
    compact = {}
    for key, value in context.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
        elif isinstance(value, list):
            compact[key] = value[:5]
        elif isinstance(value, dict):
            compact[key] = {k: value[k] for k in list(value.keys())[:8]}
        else:
            compact[key] = str(value)[:300]
    return compact


async def _small_executor_decide(plan: UpgradePlan, step: PlanStep, context: Dict) -> Dict:
    """
    Ask the cheap local model to confirm/resolve one upgrade system action.
    On local model failure, falls back to the deterministic planned action and records it.
    """
    if step.executor != "system":
        return {"action": step.action, "args": {}, "confidence": 1.0, "reason": "non-system step"}

    allowed = step.allowed_actions or [step.action]
    system = (
        "你係 URUK self-upgrade 嘅本地細模型 executor。"
        "大模型已經設計升級規則；你只負責當前一步選擇/確認 action。"
        "只輸出 JSON。格式："
        '{"action":"<allowed action 或 __blocked__>","args":{},"requires_human":false,'
        '"confidence":0.0,"reason":"短句"}。'
        "不可新增 action，不可改變步驟順序。資料不足或高風險就用 __blocked__。"
    )
    message = json.dumps({
        "plan_id": plan.plan_id,
        "mode": plan.mode,
        "execution_contract": plan.execution_contract or DEFAULT_EXECUTION_CONTRACT,
        "step": {
            "action": step.action,
            "description": step.description,
            "executor_rule": step.executor_rule,
            "allowed_actions": allowed,
            "success_criteria": step.success_criteria,
        },
        "context": _small_executor_context(context),
    }, ensure_ascii=False)

    event = {
        "timestamp": datetime.now().isoformat(),
        "step": step.action,
        "allowed_actions": allowed,
    }
    try:
        from services.task_profiles import get_task_profile, profile_api_key
        from services.local_llm_discovery import quick_chat

        profile = get_task_profile("small", APP_ROOT / "config")
        raw = await quick_chat(
            api_base=profile.get("api_base") or "http://localhost:11434",
            provider=profile.get("provider") or "ollama",
            model=profile.get("model") or "qwen2.5:3b",
            message=message,
            system=system,
            timeout=float(profile.get("timeout_seconds") or 3.0),
            api_key=profile_api_key(profile),
            max_tokens=256,
        )
        decision = _extract_json_object(raw) or {}
        action = str(decision.get("action") or step.action)
        event.update({"raw": raw[:500], "decision": decision})
    except Exception as e:
        action = step.action
        decision = {
            "action": action,
            "args": {},
            "requires_human": False,
            "confidence": 0.0,
            "reason": f"small executor unavailable; deterministic fallback: {type(e).__name__}: {e}",
        }
        event.update({"fallback": True, "error": decision["reason"], "decision": decision})

    if action == "__blocked__" or decision.get("requires_human") is True:
        event["outcome"] = "blocked"
        plan.executor_events.append(event)
        plan.save()
        return {"action": "__blocked__", "reason": decision.get("reason", "細模型要求人類確認")}

    if action not in allowed:
        event["outcome"] = "corrected"
        event["reason"] = f"model suggested disallowed action {action!r}; using deterministic action {step.action!r}"
        action = step.action
        decision["action"] = action

    event["outcome"] = "approved"
    event["action"] = action
    plan.executor_events.append(event)
    plan.save()
    return decision | {"action": action}


async def _run_system_step_with_small_executor(
    plan: UpgradePlan,
    action: str,
    context: Dict,
    runner,
) -> Optional[Any]:
    step = plan.get_step(action)
    if not step:
        raise ValueError(f"Unknown upgrade step: {action}")

    plan.update_step(action, "running")
    decision = await _small_executor_decide(plan, step, context)
    if decision.get("action") == "__blocked__":
        plan.update_step(action, "failed", error=str(decision.get("reason") or "blocked"))
        plan.status = "failed"
        plan.summary += f" 細模型 executor 阻止 step {action}: {decision.get('reason')}"
        plan.save()
        return None

    t0 = time.time()
    try:
        output = runner()
    except Exception as e:
        plan.update_step(action, "failed", error=f"{type(e).__name__}: {e}")
        raise
    duration_ms = int((time.time() - t0) * 1000)
    step = plan.get_step(action)
    if step:
        step.duration_ms = duration_ms
    plan.update_step(action, "done", output=output)
    return output


def _summarize_validation_failures(failures: List[Dict], limit: int = 3) -> str:
    """Return a compact user-facing summary without dumping generated code."""
    if not failures:
        return "無可顯示原因"

    parts = []
    for item in failures[:limit]:
        spec = item.get("spec") or {}
        name = spec.get("name") or "未命名工具"
        reasons = item.get("reasons") or ["未提供原因"]
        reason_text = "；".join(str(r) for r in reasons)
        parts.append(f"{name}（{reason_text}）")

    if len(failures) > limit:
        parts.append(f"另有 {len(failures) - limit} 個失敗")

    return "；".join(parts)


async def execute_plan_after_claude(plan_id: str, claude_response: str) -> UpgradePlan:
    """
    Claude 回覆後，URUK 自動執行剩餘嘅 system steps。
    Steps 6-10 全部由 URUK 自動完成。
    """
    plan = UpgradePlan.load(plan_id)

    # 解析 Claude 回覆
    plan.update_step("design_tools", "running")
    raw_response_path = _save_relay_response(plan_id, claude_response or "")
    execution_plan_meta = apply_execution_plan_from_response(plan, claude_response)
    specs = parse_claude_response(plan_id, claude_response)
    plan.tool_specs = specs
    plan.update_step("design_tools", "done", output={
        "specs_parsed": len(specs),
        "execution_plan": execution_plan_meta,
        "raw_response_path": raw_response_path,
        "raw_response_preview": (claude_response or "")[:1200],
    })

    if not specs:
        plan.status = "failed"
        plan.summary += f" Claude 回覆中未找到有效 [TOOL_SPEC] 區塊。原始回覆已保存：{raw_response_path}"
        plan.save()
        return plan

    plan.status = "installing"
    plan.save()

    # Step 6: validate
    validation = await _run_system_step_with_small_executor(
        plan,
        "validate_code",
        {"spec_count": len(specs), "spec_names": [s.get("name") for s in specs]},
        lambda: step_validate_tool_specs(specs),
    )
    if validation is None:
        return plan
    plan.review_tool_specs = [item["spec"] for item in validation.get("needs_review", [])]
    plan.get_step("validate_code").output = {
        "passed": validation["pass_count"],
        "failed": validation["fail_count"],
        "review": validation.get("review_count", 0),
        "failures": [f["reasons"] for f in validation["failed"]],
        "review_reasons": [r["reasons"] for r in validation.get("needs_review", [])],
    }
    plan.save()

    if not validation["passed"]:
        if validation.get("needs_review"):
            plan.status = "review_required"
            plan.summary += (
                f" {validation.get('review_count', 0)} 個工具需要人工確認，"
                f"{validation['fail_count']} 個工具未通過驗證；未自動安裝。"
            )
        else:
            plan.status = "failed"
            plan.summary += f" 所有工具驗證失敗：{_summarize_validation_failures(validation['failed'])}"
        plan.save()
        return plan

    # Step 7: pre-install snapshot
    snapshot = await _run_system_step_with_small_executor(
        plan,
        "pre_install_snapshot",
        {
            "passed_count": validation["pass_count"],
            "install_names": [s.get("name") for s in validation["passed"]],
        },
        lambda: step_pre_install_snapshot(plan),
    )
    if snapshot is None:
        return plan

    # Step 8: install
    installed = await _run_system_step_with_small_executor(
        plan,
        "install_tools",
        {
            "passed_count": validation["pass_count"],
            "failed_count": validation["fail_count"],
            "install_names": [s.get("name") for s in validation["passed"]],
        },
        lambda: step_install_tools(validation["passed"]),
    )
    if installed is None:
        return plan
    plan.installed_tools = installed
    plan.get_step("install_tools").output = {"installed": installed}
    plan.save()

    # Step 8: hot reload
    reload_result = await _run_system_step_with_small_executor(
        plan,
        "hot_reload",
        {"installed": installed},
        step_hot_reload,
    )
    if reload_result is None:
        return plan
    missing_reload = [name for name in installed if name not in (reload_result.get("reloaded") or [])]
    if missing_reload:
        plan.status = "failed"
        plan.summary += f" Hot reload 未能載入工具：{missing_reload}"
        plan.save()
        return plan

    # Step 9: smoke test
    test_result = await _run_system_step_with_small_executor(
        plan,
        "smoke_test",
        {"installed": installed, "reload_result": reload_result},
        lambda: step_smoke_test(installed),
    )
    if test_result is None:
        return plan
    smoke_failed = test_result.get("failed", [])
    if smoke_failed:
        plan.status = "failed"
        plan.summary += f" Smoke test 失敗：{smoke_failed}"
        plan.save()
        return plan

    # Step 10: post-install eval (benchmark quick_eval vs baseline; rollback on regression)
    eval_result = await _run_system_step_with_small_executor(
        plan,
        "post_install_eval",
        {"installed": installed, "smoke_passed": test_result.get("passed", [])},
        lambda: step_post_install_eval(plan, installed),
    )
    if eval_result is None:
        return plan
    if eval_result.get("regressed"):
        # step_post_install_eval already set plan.status = "rolled_back" and saved
        return plan

    # Step 11: write log (with eval_delta if available)
    log_result = await _run_system_step_with_small_executor(
        plan,
        "write_log",
        {"installed": installed, "smoke_passed": test_result.get("passed", [])},
        lambda: (step_write_log(plan, installed, eval_result) or {"logged": len(installed)}),
    )
    if log_result is None:
        return plan

    plan.status = "done"
    smoke_passed = test_result.get("passed", [])
    review_suffix = ""
    if plan.review_tool_specs:
        review_suffix = f" {len(plan.review_tool_specs)} 個高風險工具已保留為人工確認，未自動安裝。"
    eval_suffix = ""
    if eval_result and not eval_result.get("skipped") and not eval_result.get("regressed"):
        d_iou = eval_result.get("framing_iou_delta", 0.0)
        d_chain = eval_result.get("chain_match_delta", 0.0)
        eval_suffix = f" Eval: framing_iou Δ={d_iou:+.3f}, chain_match Δ={d_chain:+.3f}."
    elif eval_result and (eval_result.get("benchmark") or {}).get("passed"):
        bench = eval_result.get("benchmark") or {}
        eval_suffix = (
            f" Benchmark: {bench.get('passed_count', 0)}/"
            f"{bench.get('case_count', 0)} deterministic cases passed."
        )
    plan.summary = (
        f"✅ 升級完成。安裝 {len(installed)} 個工具：{', '.join(installed)}。"
        + (f" Smoke test 通過：{smoke_passed}。" if smoke_passed else "")
        + eval_suffix
        + review_suffix
    )
    plan.save()
    return plan


# ─────────────────────────────────────────────────────────────────
# Public API (called by app.py endpoints)
# ─────────────────────────────────────────────────────────────────

def list_plans(limit: int = 20) -> List[Dict]:
    """返回最近 N 個計劃書摘要。"""
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(PLANS_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    result = []
    for f in files[:limit]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({
                "plan_id": data["plan_id"],
                "mode": data["mode"],
                "status": data["status"],
                "created_at": data["created_at"],
                "summary": data.get("summary", ""),
                "installed_tools": data.get("installed_tools", []),
                "snapshots": data.get("snapshots", {}),
                "review_count": len(data.get("review_tool_specs", [])),
                "gap_count": len(data.get("gaps", [])),
            })
        except Exception:
            pass
    return result
