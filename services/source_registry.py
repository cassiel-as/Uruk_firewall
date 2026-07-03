"""
URUK Trinity Console — SourceCoordinateRegistry (v8.14 BN-2)

Four-tier source rating + declared coordinate for BrowserNode audit.
Per protocol spec: "claimed neutral" sources are downgraded to UNVERIFIED;
explicitly positioned sources can attain PROBABLE / VERIFIED.

Tiers:
    VERIFIED    — Peer-reviewed / institutional with reproducible methodology
    PROBABLE    — Declared coordinate, established editorial process
    INFERRED    — Declared coordinate, partisan / state-aligned editorial process
    UNVERIFIED  — Unknown domain, anonymous, or claims "neutral" without basis

Public API:
    SourceCoordinateRegistry().audit(url, content) -> dict
    SourceCoordinateRegistry().add_mapping(domain, coordinate, rating) -> bool
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

OVERLAY_PATH_DEFAULT = Path(__file__).parent.parent / "data" / "source_registry_overlay.json"
OVERLAY_SCHEMA_VERSION = "1.0"


# Seed mapping. Editable at runtime via add_mapping() — UI Settings tab can
# expose this later. Coordinates are declarative (where does this voice
# speak FROM), not partisan labels.
KNOWN_COORDINATES: Dict[str, Dict[str, str]] = {
    # Peer-reviewed / institutional
    "nature.com":         {"coordinate": "Peer-reviewed science",       "rating": "VERIFIED"},
    "science.org":        {"coordinate": "Peer-reviewed science",       "rating": "VERIFIED"},
    "nih.gov":            {"coordinate": "US public health institute",  "rating": "VERIFIED"},
    "who.int":            {"coordinate": "UN health agency",            "rating": "VERIFIED"},
    "arxiv.org":          {"coordinate": "Pre-print academic",          "rating": "PROBABLE"},
    "ssrn.com":           {"coordinate": "Pre-print social sciences",   "rating": "PROBABLE"},

    # Established news with declared editorial process
    "reuters.com":        {"coordinate": "UK/global news agency",       "rating": "PROBABLE"},
    "apnews.com":         {"coordinate": "US news cooperative",         "rating": "PROBABLE"},
    "bbc.com":            {"coordinate": "UK public broadcaster",       "rating": "PROBABLE"},
    "bbc.co.uk":          {"coordinate": "UK public broadcaster",       "rating": "PROBABLE"},
    "nytimes.com":        {"coordinate": "US liberal-positioned daily", "rating": "PROBABLE"},
    "wsj.com":            {"coordinate": "US conservative-positioned",  "rating": "PROBABLE"},
    "ft.com":             {"coordinate": "UK financial daily",          "rating": "PROBABLE"},
    "economist.com":      {"coordinate": "UK liberal weekly",           "rating": "PROBABLE"},
    "scmp.com":           {"coordinate": "Hong Kong English media",     "rating": "PROBABLE"},
    "theguardian.com":    {"coordinate": "UK liberal-positioned",       "rating": "PROBABLE"},

    # State-aligned outlets (declared coordinate; rating INFERRED — verify via cross-source)
    "xinhuanet.com":      {"coordinate": "PRC state media",             "rating": "INFERRED"},
    "globaltimes.cn":     {"coordinate": "PRC state media",             "rating": "INFERRED"},
    "people.cn":          {"coordinate": "PRC state media",             "rating": "INFERRED"},
    "cctv.com":           {"coordinate": "PRC state media",             "rating": "INFERRED"},
    "rt.com":             {"coordinate": "Russian state media",         "rating": "INFERRED"},
    "tass.com":           {"coordinate": "Russian state news agency",   "rating": "INFERRED"},
    "presstv.ir":         {"coordinate": "Iranian state media",         "rating": "INFERRED"},
    "aljazeera.com":      {"coordinate": "Qatari state-funded",         "rating": "INFERRED"},
    "voanews.com":        {"coordinate": "US government broadcaster",   "rating": "INFERRED"},

    # Mixed-authorship / crowd-edited
    "wikipedia.org":      {"coordinate": "Crowd-edited reference",      "rating": "PROBABLE"},
    "github.com":         {"coordinate": "Open-source code repo",       "rating": "PROBABLE"},
    "stackoverflow.com":  {"coordinate": "Q&A community",               "rating": "PROBABLE"},

    # Self-published / mixed
    "medium.com":         {"coordinate": "Self-published essay",        "rating": "INFERRED"},
    "substack.com":       {"coordinate": "Subscription newsletter",     "rating": "INFERRED"},
    "twitter.com":        {"coordinate": "Mixed authorship platform",   "rating": "UNVERIFIED"},
    "x.com":              {"coordinate": "Mixed authorship platform",   "rating": "UNVERIFIED"},
    "facebook.com":       {"coordinate": "Mixed authorship platform",   "rating": "UNVERIFIED"},
    "reddit.com":         {"coordinate": "Mixed authorship forum",      "rating": "UNVERIFIED"},
    "youtube.com":        {"coordinate": "Video / mixed authorship",    "rating": "UNVERIFIED"},
    "tiktok.com":         {"coordinate": "Video / mixed authorship",    "rating": "UNVERIFIED"},

    # Major HK media examples (variety of coords)
    "hk01.com":           {"coordinate": "Hong Kong Chinese media",     "rating": "INFERRED"},
    "rthk.hk":            {"coordinate": "Hong Kong public broadcaster","rating": "PROBABLE"},
    "mingpao.com":        {"coordinate": "Hong Kong Chinese daily",     "rating": "INFERRED"},
    "appledaily.com":     {"coordinate": "Hong Kong Chinese daily (defunct)", "rating": "INFERRED"},
    "hkfp.com":           {"coordinate": "Hong Kong English independent","rating": "PROBABLE"},
}


# Tier ordering helps fusion: higher tier > lower tier for ranking sources.
RATING_ORDER = ["VERIFIED", "PROBABLE", "INFERRED", "UNVERIFIED"]


# v8.1 Framing Patterns — multi-pattern detection downgrade trigger.
# Lightweight regex heuristics for surface-level scan. Each pattern matches
# the v8.1 toolkit ID 9-13 from news_filter.md §IV.
FRAMING_PATTERN_RULES = [
    # 9. Surgical / Precision normalization
    (9, "surgical_precision",
     r"\b(surgical|precision|pinpoint|targeted)\s+(strike|operation|attack|elimination|killing|targeting)\b|"
     r"精準\s*(打擊|空襲|清除|定點)|外科手術式"),
    # 10. Mandate inflation
    (10, "mandate_inflation",
     r"\b(historic|sweeping|overwhelming|decisive|unprecedented|landslide)\s+(mandate|victory|win|popular vote)\b|"
     r"\b(strong|clear|decisive)\s+mandate\b|歷史性\s*(授權|勝利|委任)"),
    # 11. Telegraphic strike normalization
    (11, "telegraphic_strike",
     r"\b(telegraphed|advance(d)?\s+warning|pre[- ]?announced|signal(l)?ed)\s+(strike|attack|response|retaliation)\b|"
     r"\b(measured|calibrated|proportionate)\s+(response|retaliation|strike)\b|"
     r"預告\s*打擊|有限(規模)?報復"),
    # 12. Carcass narrative
    (12, "carcass_narrative",
     r"\b(decapitation|beheading|kill(ing)?\s+the\s+head|elimination\s+of\s+(leader|chief|commander))\b|"
     r"\b(end|finish|destroy|collapse)(s|ed)?\s+(of\s+)?(the\s+)?(organization|movement|group|regime)\b|"
     r"斬首\s*行動|斬\s*(首腦|首領)"),
    # 13. Generational identity collapse
    (13, "generational_collapse",
     r"\b(gen[- ]?z|gen[- ]?x|gen[- ]?y|millennial|boomer|generation\s+[a-z])\s+(revolution|uprising|protest|movement|collapse|crisis)\b|"
     r"\b(generational|cohort)\s+(divide|war|conflict|gap|collapse)\b|"
     r"(?:Z\s*世代|世代\s*(?:革命|衝突|戰爭|對立))"),
]

# Downgrade rule: 2+ v8.1 patterns detected → rating drops 1 tier (toward UNVERIFIED).
FRAMING_DOWNGRADE_THRESHOLD = 2


def _detect_framing_patterns(content: str) -> Dict:
    """Scan content for v8.1 framing patterns 9-13.

    Returns: {detected: [ids], names: [names], chain_position: bool}
    chain_position = True when 2+ patterns co-occur (per spec meta-structure).
    """
    import re
    if not content:
        return {"detected": [], "names": [], "chain_position": False}
    text = content[:50_000]  # cap scan window for perf
    hits = []
    names = []
    for pid, name, pattern in FRAMING_PATTERN_RULES:
        try:
            if re.search(pattern, text, re.IGNORECASE):
                hits.append(pid)
                names.append(name)
        except re.error:
            continue
    return {
        "detected": hits,
        "names": names,
        "chain_position": len(hits) >= FRAMING_DOWNGRADE_THRESHOLD,
    }


def _downgrade_rating(rating: str, steps: int = 1) -> str:
    """Move rating toward UNVERIFIED by `steps` tiers. Clamped at UNVERIFIED."""
    try:
        idx = RATING_ORDER.index(rating)
    except ValueError:
        return "UNVERIFIED"
    new_idx = min(idx + max(0, steps), len(RATING_ORDER) - 1)
    return RATING_ORDER[new_idx]


class SourceCoordinateRegistry:
    """Audit fetched sources against known-coordinate registry.

    v8.15 MS-2: user-defined overrides persist to `data/source_registry_overlay.json`.
    Lookup priority: overlay > seed (KNOWN_COORDINATES) > UNVERIFIED default.
    """

    def __init__(self, mapping: Optional[Dict[str, Dict[str, str]]] = None,
                 overlay_path: Optional[Path] = None):
        # Lowercased domain → {coordinate, rating}
        self._seed = dict(KNOWN_COORDINATES) if mapping is None else dict(mapping)
        self.overlay_path = Path(overlay_path) if overlay_path else OVERLAY_PATH_DEFAULT
        self._overlay: Dict[str, Dict[str, str]] = {}
        self._load_overlay()
        self._mapping = self._effective_mapping()

    def _effective_mapping(self) -> Dict[str, Dict[str, str]]:
        merged = dict(self._seed)
        merged.update(self._overlay)  # overlay wins
        return merged

    def _load_overlay(self) -> None:
        if not self.overlay_path.exists():
            self._overlay = {}
            return
        try:
            data = json.loads(self.overlay_path.read_text(encoding="utf-8"))
            mappings = data.get("mappings", {}) if isinstance(data, dict) else {}
            cleaned: Dict[str, Dict[str, str]] = {}
            for d, v in mappings.items():
                if not isinstance(v, dict):
                    continue
                rating = v.get("rating", "")
                if rating not in RATING_ORDER:
                    continue
                cleaned[d.lower().strip()] = {
                    "coordinate": str(v.get("coordinate", "")).strip(),
                    "rating": rating,
                }
            self._overlay = cleaned
        except Exception as e:
            log.warning("source_registry overlay load failed: %s: %s", type(e).__name__, e)
            self._overlay = {}

    def _save_overlay(self) -> bool:
        try:
            self.overlay_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": OVERLAY_SCHEMA_VERSION,
                "domain_count": len(self._overlay),
                "mappings": self._overlay,
            }
            self.overlay_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception as e:
            log.warning("source_registry overlay save failed: %s: %s", type(e).__name__, e)
            return False

    def audit(self, url: str, content: str = "") -> Dict:
        """Audit one fetched source.

        Returns: {url, domain, coordinate, rating, content_length,
                  framing_patterns, framing_chain_position, base_rating}
        Default rating for unknown domain = UNVERIFIED + coordinate = "unknown_unverified".

        v8.1: if 2+ framing patterns (ID 9-13) detected → rating downgrade 1 tier.
        """
        domain = self._extract_domain(url)
        known = self._lookup(domain)
        base_rating = known.get("rating", "UNVERIFIED") if known else "UNVERIFIED"
        framing = _detect_framing_patterns(content)

        # Multi-pattern downgrade
        if framing["chain_position"]:
            final_rating = _downgrade_rating(base_rating, steps=1)
        else:
            final_rating = base_rating

        return {
            "url": url,
            "domain": domain,
            "coordinate": known.get("coordinate", "unknown_unverified") if known else "unknown_unverified",
            "rating": final_rating,
            "base_rating": base_rating,
            "content_length": len(content or ""),
            "framing_patterns": framing["detected"],
            "framing_pattern_names": framing["names"],
            "framing_chain_position": framing["chain_position"],
        }

    # ─────────── CRUD (overlay-persisted, MS-2) ───────────

    def add_mapping(self, domain: str, coordinate: str, rating: str) -> bool:
        """Add or override a domain mapping. Persists to overlay JSON.

        Returns True on success, False on invalid input.
        """
        if not domain or not coordinate or rating not in RATING_ORDER:
            return False
        d = domain.lower().strip()
        self._overlay[d] = {"coordinate": coordinate.strip(), "rating": rating}
        self._mapping = self._effective_mapping()
        return self._save_overlay()

    def update_mapping(self, domain: str, coordinate: Optional[str] = None,
                       rating: Optional[str] = None) -> bool:
        """Update an existing mapping (overlay layer only).

        If the domain is only in the seed, this creates an overlay entry that
        shadows it. Returns True on success.
        """
        if not domain:
            return False
        d = domain.lower().strip()
        existing = self._overlay.get(d) or self._seed.get(d)
        if existing is None:
            return False
        new_coord = coordinate.strip() if coordinate is not None else existing["coordinate"]
        new_rating = rating if rating is not None else existing["rating"]
        if new_rating not in RATING_ORDER:
            return False
        self._overlay[d] = {"coordinate": new_coord, "rating": new_rating}
        self._mapping = self._effective_mapping()
        return self._save_overlay()

    def delete_mapping(self, domain: str) -> bool:
        """Remove an overlay entry. Cannot delete seed entries — to hide a seed
        entry, overlay it with a different rating (or override with empty fields).

        Returns True if an overlay entry was removed.
        """
        if not domain:
            return False
        d = domain.lower().strip()
        if d not in self._overlay:
            return False
        del self._overlay[d]
        self._mapping = self._effective_mapping()
        return self._save_overlay()

    def list_mappings(self, include_origin: bool = False) -> Dict:
        """Return current effective mapping for UI / export.

        include_origin=True returns per-entry {coordinate, rating, origin}
        where origin ∈ {"seed", "overlay"}.
        """
        if not include_origin:
            return dict(self._mapping)
        out: Dict[str, Dict] = {}
        for d, v in self._mapping.items():
            origin = "overlay" if d in self._overlay else "seed"
            out[d] = {**v, "origin": origin}
        return out

    def export_json(self) -> Dict:
        """Schema-tagged snapshot — overlay-only by default (for portability)."""
        return {
            "version": OVERLAY_SCHEMA_VERSION,
            "domain_count": len(self._overlay),
            "mappings": dict(self._overlay),
        }

    def import_json(self, payload: Dict, replace: bool = False) -> Dict:
        """Bulk import. replace=False merges; replace=True overwrites overlay.

        Returns {accepted, rejected, version}.
        """
        if not isinstance(payload, dict):
            return {"accepted": 0, "rejected": 0, "error": "not_a_dict"}
        mappings = payload.get("mappings", {}) or {}
        if not isinstance(mappings, dict):
            return {"accepted": 0, "rejected": 0, "error": "mappings_must_be_dict"}
        if replace:
            self._overlay.clear()
        accepted = 0
        rejected = 0
        for d, v in mappings.items():
            if not isinstance(v, dict):
                rejected += 1
                continue
            rating = v.get("rating", "")
            coord = (v.get("coordinate") or "").strip()
            if rating not in RATING_ORDER or not coord or not d:
                rejected += 1
                continue
            self._overlay[d.lower().strip()] = {"coordinate": coord, "rating": rating}
            accepted += 1
        self._mapping = self._effective_mapping()
        self._save_overlay()
        return {"accepted": accepted, "rejected": rejected,
                "version": payload.get("version", OVERLAY_SCHEMA_VERSION)}

    def reset_overlay(self) -> bool:
        """Clear all user overrides; revert to pure seed mapping."""
        self._overlay = {}
        self._mapping = self._effective_mapping()
        return self._save_overlay()

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract bare domain, normalize (strip www., port, lowercase)."""
        if not url:
            return ""
        try:
            parsed = urlparse(url if "://" in url else f"http://{url}")
            host = (parsed.netloc or parsed.path).lower()
            host = host.split(":", 1)[0]
            if host.startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return url.lower()

    def _lookup(self, domain: str) -> Optional[Dict[str, str]]:
        """Look up domain with suffix-match fallback (e.g. blog.medium.com → medium.com)."""
        if not domain:
            return None
        if domain in self._mapping:
            return self._mapping[domain]
        # Try suffix match: split by dots, walk back
        parts = domain.split(".")
        for i in range(1, len(parts)):
            candidate = ".".join(parts[i:])
            if candidate in self._mapping:
                return self._mapping[candidate]
        return None


# Module-level singleton
source_registry = SourceCoordinateRegistry()
