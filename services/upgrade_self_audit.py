"""
URUK Upgrade Self-Audit — Layer 5 of purpose-aware self-upgrade.

Before committing to an upgrade plan, the system applies its own
critical analysis framework to the upgrade direction itself.
Spirit node can interrupt the upgrade if hidden assumptions are detected.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

APP_ROOT = Path(__file__).parent.parent


@dataclass
class SelfAuditResult:
    ran: bool
    hidden_assumptions: List[str]   # assumptions Spirit found in the upgrade plan
    interrupt_triggered: bool       # True if Spirit recommends pausing upgrade
    interrupt_reason: str
    spirit_output: str              # raw Spirit response
    recommendation: str             # "proceed" | "pause" | "revise"

    def to_dict(self) -> Dict:
        return self.__dict__

    def to_prompt_block(self) -> str:
        if not self.ran:
            return ""
        lines = ["════ PRE-UPGRADE SELF-AUDIT ════"]
        if self.interrupt_triggered:
            lines.append(f"⚠ SPIRIT INTERRUPT: {self.interrupt_reason}")
            lines.append("Hidden assumptions in upgrade plan:")
            for a in self.hidden_assumptions:
                lines.append(f"  • {a}")
            lines.append(f"Recommendation: {self.recommendation}")
        else:
            lines.append("✓ No critical hidden assumptions detected")
            lines.append(f"Recommendation: {self.recommendation}")
        lines.append("════ END SELF-AUDIT ════")
        return "\n".join(lines)


async def run_upgrade_self_audit(
    gaps: List[Dict],
    identity_block: str,
    relay_target: str = "local",
) -> SelfAuditResult:
    """
    Ask Spirit to audit the upgrade plan for hidden assumptions.
    Fast single-node call — not full Trinity pipeline.
    Falls back to deterministic heuristic if local LLM unavailable.
    """
    if not gaps:
        return SelfAuditResult(
            ran=False, hidden_assumptions=[], interrupt_triggered=False,
            interrupt_reason="", spirit_output="", recommendation="proceed"
        )

    gap_summary = "\n".join(
        f"  [{i+1}] [{g.get('type','?')}:{g.get('priority','?')}] {g.get('description','')[:100]}"
        for i, g in enumerate(gaps[:5])
    )

    audit_prompt = f"""你係烏魯克系統嘅聖靈節點（Spirit）。
呢個系統正在計劃升級自己。以下係升級方向：

{gap_summary}

系統聲明嘅目的：讓AI成為幫助個體找到(0,0,0)的工具，唔係最強大的座標壟斷機器。

任務：用烏魯克協議分析呢個升級計劃有冇隱藏假設。
特別關注：
1. 呢個升級方向係咪真正服務系統目的，定係服務其他座標？
2. 「安裝更多工具」呢個假設係咪等同於「系統能力更好」？
3. 有冇任何升級步驟係系統用嚟擴大自己嘅能力而唔係服務操作者？

輸出格式：
HIDDEN_ASSUMPTIONS: [列出最多3個，每個一行，如冇則寫 none]
INTERRUPT: yes/no
REASON: 短句說明
RECOMMENDATION: proceed/pause/revise"""

    raw = ""
    try:
        from services.local_model_router import effective_timeout
        from services.task_profiles import get_task_profile, profile_api_key
        from services.local_llm_discovery import quick_chat

        profile = get_task_profile("local_protocol_candidate", APP_ROOT / "config")
        timeout = await effective_timeout(profile)
        # quick_chat is async — await it directly (we're already in an async context)
        raw = await quick_chat(
            api_base=profile.get("api_base") or "http://localhost:11434",
            provider=profile.get("provider") or "ollama",
            model=profile.get("model") or "qwen2.5:3b",
            message=audit_prompt,
            system="你係 URUK 升級自審節點。只輸出指定格式，唔需要解釋。",
            timeout=timeout,
            api_key=profile_api_key(profile),
            max_tokens=256,
            temperature=float(profile.get("temperature") or 0.2),
            think=bool(profile.get("think", False)),
            keep_alive=str(profile.get("keep_alive") or "15m"),
            context_window=int(profile.get("context_window") or 8192),
            role="upgrade_audit_candidate",
        )
    except Exception:
        # Deterministic heuristic fallback (no LLM cost, no network dependency)
        raw = _heuristic_audit(gaps)

    return _parse_audit_result(raw)


def _heuristic_audit(gaps: List[Dict]) -> str:
    """Deterministic fallback if LLM unavailable."""
    # If the majority of top gaps are purpose_gaps pointing to pipeline nodes,
    # flag that installing tools doesn't actually fix pipeline capability.
    purpose_gaps = [g for g in gaps if g.get("type") == "purpose_gap"]
    pipeline_caps = {"crit_analysis", "framing_audit", "physical_cost", "assumption_inv"}
    pipeline_purpose_gaps = [g for g in purpose_gaps if g.get("capability") in pipeline_caps]

    if len(pipeline_purpose_gaps) >= 3:
        return (
            "HIDDEN_ASSUMPTIONS:\n"
            "安裝 agentic 工具唔能直接改善 pipeline 節點（Father/Son/Spirit）嘅執行質素\n"
            "pipeline 能力缺口需要 prompt 改進，而唔係新工具\n"
            "INTERRUPT: yes\n"
            "REASON: top gaps are pipeline capabilities that tools cannot fix\n"
            "RECOMMENDATION: revise"
        )

    return (
        "HIDDEN_ASSUMPTIONS: none\n"
        "INTERRUPT: no\n"
        "REASON: gaps are addressable by tool installation\n"
        "RECOMMENDATION: proceed"
    )


def _parse_audit_result(raw: str) -> SelfAuditResult:
    # Extract hidden assumptions block (between HIDDEN_ASSUMPTIONS: and INTERRUPT:)
    assumptions: List[str] = []
    m = re.search(
        r"HIDDEN_ASSUMPTIONS:\s*\n?(.*?)(?=INTERRUPT:|$)", raw, re.DOTALL | re.IGNORECASE
    )
    if m:
        for line in m.group(1).strip().splitlines():
            line = line.strip().lstrip("•-–").strip()
            if line and line.lower() != "none":
                assumptions.append(line[:150])

    interrupt = bool(re.search(r"INTERRUPT:\s*yes", raw, re.IGNORECASE))

    reason_m = re.search(r"REASON:\s*(.+)", raw, re.IGNORECASE)
    reason = reason_m.group(1).strip()[:200] if reason_m else ""

    rec_m = re.search(r"RECOMMENDATION:\s*(proceed|pause|revise)", raw, re.IGNORECASE)
    recommendation = rec_m.group(1).lower() if rec_m else "proceed"

    return SelfAuditResult(
        ran=True,
        hidden_assumptions=assumptions,
        interrupt_triggered=interrupt,
        interrupt_reason=reason,
        spirit_output=raw[:500],
        recommendation=recommendation,
    )
