"""URUK System Identity — Layer 1 of purpose-aware self-upgrade."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

APP_ROOT = Path(__file__).parent.parent

CANONICAL_LOCK: Dict = {
    "lie_cost": 5.85, "freedom_loss_entropy": 8.19,
    "operator_anchor": "2019-06-12", "spatial_anchor": "Leeds (53.8, -1.5, 0)",
    "omega_anchor": "2045",
    "purpose": "讓AI成為幫助個體找到(0,0,0)的工具，唔係最強大的座標壟斷機器",
}

REQUIRED_CAPABILITIES = [
    ("crit_analysis",  "批判性分析語言嘅隱藏假設同框架",        ["firewall","filter","blackbox","delabel"]),
    ("coord_detection","識別陳述背後嘅座標（誰講、從哪裏講）",   ["scr","source_coordinate","dispatcher"]),
    ("framing_audit",  "過濾 framing attack 同 formatting attack",["news","framing","delabel"]),
    ("physical_cost",  "追蹤決定嘅物理代價（承受者係誰）",       ["son","veto","physical"]),
    ("assumption_inv", "識別並逆轉隱藏假設",                   ["blackbox","sovereign","spirit"]),
    ("memory_kairos",  "跨 session 記憶同密度審計",             ["kairos","density"]),
    ("voice_io",       "廣東話/普通話/英文語音輸入輸出",         ["speak_text","transcribe_audio","listen_audio"]),
    ("ext_learning",   "從外部資源（新聞/論文/RSS）主動學習",    ["fetch_hn","search_arxiv","fetch_rss_feed","fetch_webpage"]),
]

@dataclass
class CapabilityStatus:
    capability_id: str
    description: str
    required_keywords: List[str]
    installed_tools: List[str] = field(default_factory=list)
    coverage_score: float = 0.0

@dataclass
class SystemIdentity:
    purpose: str
    operator_anchor: str
    canonical_lock: Dict
    capabilities: List[CapabilityStatus]
    declared_version: str

    def missing_capabilities(self): return [c for c in self.capabilities if c.coverage_score < 0.3]
    def weak_capabilities(self): return [c for c in self.capabilities if 0.3 <= c.coverage_score < 0.7]

    def to_prompt_block(self) -> str:
        lines = ["════ SYSTEM IDENTITY ════", f"Purpose: {self.purpose}",
                 f"Version: {self.declared_version}", f"Operator anchor: {self.operator_anchor}", "",
                 "Capability coverage (✓ strong, △ partial, ✗ missing):"]
        for cap in self.capabilities:
            s = "✓" if cap.coverage_score >= 0.7 else ("△" if cap.coverage_score >= 0.3 else "✗")
            tools = ", ".join(cap.installed_tools[:3]) or "none"
            lines.append(f"  {s} [{cap.capability_id}] {cap.description} ({cap.coverage_score:.0%}) — {tools}")
        lines += ["", "Canonical lock — NEVER modify via upgrade:",
                  *[f"  • {k}: {v}" for k,v in self.canonical_lock.items()],
                  "════ END SYSTEM IDENTITY ════"]
        return "\n".join(lines)

    def to_dict(self):
        return {"purpose": self.purpose, "version": self.declared_version,
                "operator_anchor": self.operator_anchor, "canonical_lock": self.canonical_lock,
                "capabilities": [{"id":c.capability_id,"description":c.description,"score":c.coverage_score,"tools":c.installed_tools} for c in self.capabilities],
                "missing": [c.capability_id for c in self.missing_capabilities()],
                "weak":    [c.capability_id for c in self.weak_capabilities()]}

def _extract_version(text):
    m = re.search(r"v(\d+\.\d+[\w\.]*)", text[:500])
    return m.group(0) if m else "v8.x"

def _assess_capability(cap_tuple, registry):
    cap_id, description, keywords = cap_tuple
    installed = [n for n in registry if any(kw.lower() in n.lower() for kw in keywords)]
    families_matched = sum(1 for kw in keywords if any(kw.lower() in n.lower() for n in registry))
    score = round(min(1.0, families_matched / len(keywords)), 2)
    return CapabilityStatus(cap_id, description, keywords, installed, score)

def load_system_identity() -> SystemIdentity:
    skill_path = APP_ROOT / "config" / "protocol" / "SKILL.md"
    skill_text = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""
    version = _extract_version(skill_text)
    try:
        from services.computer_tools import TOOL_REGISTRY
        registry = dict(TOOL_REGISTRY)
    except Exception:
        registry = {}
    capabilities = [_assess_capability(cap, registry) for cap in REQUIRED_CAPABILITIES]
    return SystemIdentity(CANONICAL_LOCK["purpose"], CANONICAL_LOCK["operator_anchor"],
                          CANONICAL_LOCK, capabilities, version)

_IDENTITY: Optional[SystemIdentity] = None

def get_identity() -> SystemIdentity:
    global _IDENTITY
    if _IDENTITY is None: _IDENTITY = load_system_identity()
    return _IDENTITY

def refresh_identity() -> SystemIdentity:
    global _IDENTITY
    _IDENTITY = load_system_identity()
    return _IDENTITY
