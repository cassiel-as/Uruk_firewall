"""
URUK Density Bridge — Layer 3 of purpose-aware self-upgrade.

Reads §4.6 density signals from KAIROS_LOG and recent sessions,
converts them into structured upgrade gaps.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict

APP_ROOT = Path(__file__).parent.parent
KAIROS_LOG = APP_ROOT / "data" / "kairos" / "KAIROS_LOG_UPDATED_v8.md"
HISTORY_DIR = APP_ROOT / "data" / "conversation_history"

# §4.6 signal detection patterns (mirrors density_audit.py)
SIGNAL_PATTERNS = {
    "operator_catch": [
        r"你又用", r"you missed", r"correction:", r"that'?s incorrect",
        r"冇做到", r"你唔係應該", r"operator.*catch",
    ],
    "carrier_self_surface": [
        r"我頭先漏咗", r"I just realized", r"on second thought",
        r"§4\.\d+ violation", r"載體邊界", r"carrier.*error",
    ],
    "same_pattern_recurrence": [
        r"RECURRENCE", r"same_pattern", r"反覆", r"again.*same",
    ],
    "tool_mechanism_emergence": [
        r"新.*工具", r"new tool", r"introducing.*mechanism", r"誕生",
        r"tool.*emergence",
    ],
    "declared_canonical_change": [
        r"canonical.*change", r"axiom.*update", r"protocol.*revision",
        r"正式.*改", r"ARCHITECTURE_RECORD",
    ],
}

@dataclass
class DensityGap:
    gap_id: str
    signal_type: str          # which §4.6 signal triggered this
    priority: str             # "critical" | "high" | "medium"
    description: str
    evidence: str             # quoted excerpt or summary
    session_count: int        # how many sessions showed this signal
    suggested_action: str     # what kind of tool/fix would address this

    def to_upgrade_gap(self) -> Dict:
        """Format as upgrade_engine gap dict."""
        return {
            "id":          self.gap_id,
            "type":        "density_gap",
            "signal":      self.signal_type,
            "priority":    self.priority,
            "description": self.description,
            "evidence":    self.evidence,
            "sessions":    self.session_count,
            "action":      self.suggested_action,
        }


def _scan_recent_sessions(days_back: int = 14) -> List[str]:
    """Return text content of recent session files."""
    from datetime import datetime, timedelta
    texts = []
    cutoff = datetime.now() - timedelta(days=days_back)
    if not HISTORY_DIR.exists():
        return texts
    for day_dir in sorted(HISTORY_DIR.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            dir_date = datetime.strptime(day_dir.name, "%Y-%m-%d")
        except ValueError:
            continue
        if dir_date >= cutoff:
            for f in day_dir.glob("trinity_*.md"):
                try:
                    texts.append(f.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
    return texts


def _scan_kairos_log() -> str:
    """Return last 200 lines of KAIROS_LOG."""
    if not KAIROS_LOG.exists():
        return ""
    try:
        lines = KAIROS_LOG.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[-200:])
    except Exception:
        return ""


def _load_installed_tool_names() -> List[str]:
    """Return tool names from the upgrade log (last 30 entries)."""
    log_path = APP_ROOT / "data" / "upgrade_log.jsonl"
    installed: List[str] = []
    if not log_path.exists():
        return installed
    try:
        for line in log_path.read_text(encoding="utf-8").strip().splitlines()[-30:]:
            entry = __import__("json").loads(line)
            name = entry.get("tool_name", "")
            if name:
                installed.append(name.lower())
    except Exception:
        pass
    return installed


# Per-signal domain keywords: if any installed tool name contains one of these,
# the corresponding density gap is suppressed (already addressed).
_SIGNAL_ADDRESSED_BY: Dict[str, List[str]] = {
    "carrier_self_surface": ["blindspot", "self_surface", "self_blind", "carrier_error", "self_identify"],
    "operator_catch":       ["compliance_checker", "protocol_check", "operator_catch"],
    "same_pattern_recurrence": ["recurrence", "pattern_detect", "loop_detect"],
    "tool_mechanism_emergence": ["kairos_log", "mechanism", "emergence", "kairos_anal"],
    "declared_canonical_change": ["canonical_change", "protocol_rev"],
}


def scan_density_gaps(days_back: int = 14) -> List[DensityGap]:
    """
    Scan recent sessions + KAIROS_LOG for §4.6 signals.
    Returns structured DensityGap list, sorted by priority.
    Suppresses gaps whose domain has already been addressed by an installed tool
    (same deduplication pattern as performance_gap_scan in upgrade_engine.py).
    """
    sessions = _scan_recent_sessions(days_back)
    kairos_text = _scan_kairos_log()
    all_text = "\n".join(sessions) + "\n" + kairos_text

    # Cross-reference upgrade log to find already-addressed signals
    installed_names = _load_installed_tool_names()
    _addressed_signals: set = set()
    for signal, keywords in _SIGNAL_ADDRESSED_BY.items():
        if any(kw in tname for kw in keywords for tname in installed_names):
            _addressed_signals.add(signal)

    signal_hits: Dict[str, int] = {s: 0 for s in SIGNAL_PATTERNS}
    signal_excerpts: Dict[str, str] = {s: "" for s in SIGNAL_PATTERNS}

    for signal, patterns in SIGNAL_PATTERNS.items():
        for pat in patterns:
            matches = re.findall(f".{{0,60}}{pat}.{{0,60}}", all_text, re.IGNORECASE)
            if matches:
                signal_hits[signal] += len(matches)
                if not signal_excerpts[signal]:
                    signal_excerpts[signal] = matches[0].strip()[:120]

    gaps: List[DensityGap] = []

    # operator_catch → highest priority: system is making recurring mistakes operator has to correct
    if signal_hits["operator_catch"] > 0 and "operator_catch" not in _addressed_signals:
        gaps.append(DensityGap(
            gap_id=f"density_operator_catch_{signal_hits['operator_catch']}",
            signal_type="operator_catch",
            priority="critical",
            description=(
                f"操作者喺 {signal_hits['operator_catch']} 次互動中需要修正系統輸出。"
                "呢個係協議執行失誤嘅直接證據。"
            ),
            evidence=signal_excerpts["operator_catch"],
            session_count=signal_hits["operator_catch"],
            suggested_action=(
                "設計一個 protocol_compliance_checker 工具，"
                "在 Council 輸出前驗證輸出係咪符合當前 mode 嘅協議要求。"
            ),
        ))

    # carrier_self_surface → high priority: system identified its own gap
    if signal_hits["carrier_self_surface"] > 0 and "carrier_self_surface" not in _addressed_signals:
        gaps.append(DensityGap(
            gap_id=f"density_self_surface_{signal_hits['carrier_self_surface']}",
            signal_type="carrier_self_surface",
            priority="high",
            description=(
                f"系統自身喺 {signal_hits['carrier_self_surface']} 次識別到自己嘅盲點或違反。"
                "呢個信號表示協議有邊個執行點係薄弱嘅。"
            ),
            evidence=signal_excerpts["carrier_self_surface"],
            session_count=signal_hits["carrier_self_surface"],
            suggested_action=(
                "分析自我識別嘅內容，設計針對呢個具體弱點嘅工具或 prompt patch。"
            ),
        ))

    # same_pattern_recurrence → high priority: same failure repeating
    if signal_hits["same_pattern_recurrence"] > 1 and "same_pattern_recurrence" not in _addressed_signals:
        gaps.append(DensityGap(
            gap_id=f"density_recurrence_{signal_hits['same_pattern_recurrence']}",
            signal_type="same_pattern_recurrence",
            priority="high",
            description=(
                f"同一個失敗模式重複出現 {signal_hits['same_pattern_recurrence']} 次。"
                "系統未能從之前嘅失誤學習。"
            ),
            evidence=signal_excerpts["same_pattern_recurrence"],
            session_count=signal_hits["same_pattern_recurrence"],
            suggested_action=(
                "設計一個 recurrence_detector 工具，在分析前先比對 Kairos log "
                "識別呢個 pattern 係咪已有歷史記錄，避免重複犯同一錯誤。"
            ),
        ))

    # tool_mechanism_emergence → medium: opportunity for new capability
    if signal_hits["tool_mechanism_emergence"] > 0 and "tool_mechanism_emergence" not in _addressed_signals:
        gaps.append(DensityGap(
            gap_id=f"density_emergence_{signal_hits['tool_mechanism_emergence']}",
            signal_type="tool_mechanism_emergence",
            priority="medium",
            description=(
                f"Kairos log 顯示有 {signal_hits['tool_mechanism_emergence']} 個"
                "新工具或機制需求湧現。"
            ),
            evidence=signal_excerpts["tool_mechanism_emergence"],
            session_count=signal_hits["tool_mechanism_emergence"],
            suggested_action="根據 Kairos log 嘅具體描述設計對應工具。",
        ))

    # Sort: critical first, then high, then medium
    priority_order = {"critical": 0, "high": 1, "medium": 2}
    gaps.sort(key=lambda g: priority_order.get(g.priority, 3))

    return gaps


def density_gaps_for_upgrade() -> List[Dict]:
    """Return gaps formatted as upgrade_engine gap dicts."""
    return [g.to_upgrade_gap() for g in scan_density_gaps()]
