"""
URUK Performance Reality — Layer 2 of purpose-aware self-upgrade.
Tracks protocol fidelity metrics across recent sessions.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

APP_ROOT = Path(__file__).parent.parent
HISTORY_DIR = APP_ROOT / "data" / "conversation_history"
BASELINES_PATH = APP_ROOT / "data" / "upgrade_baselines.json"

@dataclass
class ProtocolFidelitySnapshot:
    timestamp: str
    sessions_analyzed: int
    # Council verdict distribution
    consensus_rate: float   # fraction of turns with verdict=consensus
    veto_rate: float        # fraction with veto
    interrupt_rate: float   # fraction with interrupt
    # §4.6 signal frequency
    operator_catch_count: int      # how many times operator corrected system
    carrier_self_surface_count: int  # how many times system caught its own error
    # Pipeline health
    abort_rate: float       # fraction of turns that aborted early
    # Overall score: higher = better protocol execution
    fidelity_score: float   # weighted composite 0.0-1.0

    def to_dict(self) -> Dict:
        return self.__dict__

def _scan_session_files(days_back: int = 14) -> List[Path]:
    """Return session markdown files from the last N days."""
    files = []
    cutoff = datetime.now() - timedelta(days=days_back)
    if not HISTORY_DIR.exists():
        return files
    for day_dir in sorted(HISTORY_DIR.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            dir_date = datetime.strptime(day_dir.name, "%Y-%m-%d")
        except ValueError:
            continue
        if dir_date >= cutoff:
            files.extend(day_dir.glob("trinity_*.md"))
    return files

def compute_protocol_fidelity(days_back: int = 14) -> ProtocolFidelitySnapshot:
    """Analyse recent sessions and compute protocol fidelity metrics."""
    files = _scan_session_files(days_back)

    total_turns = 0
    consensus_count = 0
    veto_count = 0
    interrupt_count = 0
    abort_count = 0
    operator_catch_count = 0
    carrier_self_count = 0

    # §4.6 signal patterns
    OPERATOR_CATCH_PATTERNS = [r"你又用", r"you missed", r"correction:", r"that'?s incorrect", r"冇做到"]
    CARRIER_SELF_PATTERNS   = [r"我頭先漏咗", r"I just realized", r"on second thought", r"§4\.\d+ violation", r"載體邊界"]

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        total_turns += 1

        # Extract verdict — prefer structured header first, then prose fallback
        if re.search(r"^COUNCIL_VERDICT:\s*consensus", text, re.IGNORECASE | re.MULTILINE):
            consensus_count += 1
        elif re.search(r"^COUNCIL_VERDICT:\s*veto", text, re.IGNORECASE | re.MULTILINE):
            veto_count += 1
        elif re.search(r"^COUNCIL_VERDICT:\s*interrupt", text, re.IGNORECASE | re.MULTILINE):
            interrupt_count += 1
        elif re.search(r"verdict.*consensus", text, re.IGNORECASE):
            consensus_count += 1
        elif re.search(r"verdict.*veto", text, re.IGNORECASE):
            veto_count += 1
        elif re.search(r"verdict.*interrupt", text, re.IGNORECASE):
            interrupt_count += 1

        if re.search(r"abort_signal.*yes", text, re.IGNORECASE):
            abort_count += 1

        for pat in OPERATOR_CATCH_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                operator_catch_count += 1
                break

        for pat in CARRIER_SELF_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                carrier_self_count += 1
                break

    if total_turns == 0:
        return ProtocolFidelitySnapshot(
            timestamp=datetime.now().isoformat(),
            sessions_analyzed=0,
            consensus_rate=0.0, veto_rate=0.0, interrupt_rate=0.0,
            operator_catch_count=0, carrier_self_surface_count=0,
            abort_rate=0.0, fidelity_score=0.0
        )

    consensus_rate = round(consensus_count / total_turns, 3)
    veto_rate      = round(veto_count / total_turns, 3)
    interrupt_rate = round(interrupt_count / total_turns, 3)
    abort_rate     = round(abort_count / total_turns, 3)

    # Fidelity score: high consensus + low abort + low operator catches = good
    # operator_catch is normalised per-session (higher = worse)
    catch_penalty = min(1.0, operator_catch_count / max(1, total_turns))
    fidelity_score = round(
        (consensus_rate * 0.5)
        + ((1.0 - abort_rate) * 0.3)
        + ((1.0 - catch_penalty) * 0.2),
        3
    )

    return ProtocolFidelitySnapshot(
        timestamp=datetime.now().isoformat(),
        sessions_analyzed=total_turns,
        consensus_rate=consensus_rate,
        veto_rate=veto_rate,
        interrupt_rate=interrupt_rate,
        operator_catch_count=operator_catch_count,
        carrier_self_surface_count=carrier_self_count,
        abort_rate=abort_rate,
        fidelity_score=fidelity_score,
    )

def load_baselines() -> Dict:
    if BASELINES_PATH.exists():
        try:
            return json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_baselines(data: Dict) -> None:
    BASELINES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def record_fidelity_snapshot(label: str = "latest") -> ProtocolFidelitySnapshot:
    """Compute current fidelity and save to baselines. label = 'baseline' or 'latest'."""
    snap = compute_protocol_fidelity()
    data = load_baselines()
    if label == "baseline" and not data.get("fidelity_baseline"):
        data["fidelity_baseline"] = snap.to_dict()
    data["fidelity_latest"] = snap.to_dict()
    # Append to history
    if "fidelity_history" not in data:
        data["fidelity_history"] = []
    data["fidelity_history"].append({"label": label, **snap.to_dict()})
    data["fidelity_history"] = data["fidelity_history"][-20:]  # keep last 20
    save_baselines(data)
    return snap

def fidelity_delta() -> Optional[Dict]:
    """Return delta between baseline and latest fidelity. None if no baseline."""
    data = load_baselines()
    baseline = data.get("fidelity_baseline")
    latest   = data.get("fidelity_latest")
    if not baseline or not latest:
        return None
    return {
        "fidelity_score_delta": round(latest["fidelity_score"] - baseline["fidelity_score"], 3),
        "consensus_rate_delta": round(latest["consensus_rate"] - baseline["consensus_rate"], 3),
        "operator_catch_delta": latest["operator_catch_count"] - baseline["operator_catch_count"],
        "sessions_analyzed":    latest["sessions_analyzed"],
        "regressed":            latest["fidelity_score"] < baseline["fidelity_score"] - 0.05,
    }
