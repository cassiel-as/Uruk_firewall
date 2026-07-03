"""
§4.6 Kairos Output Density Audit — runtime enforcement.

Ports the kairos-density-audit skill's 6-step workflow into the Trinity Console
runtime so every /api/stream session runs through an output self-audit before
emitting `done`.

Important posture:
  - User input is task source / routing signal / operator feedback.
  - The audit target is the system's own output and persisted protocol behavior.
  - Never use this layer to judge whether the user is "dense enough" or
    "coordinate-aligned enough".

Carrier boundary (v8.31 — operator-directed System 2 spec):
  ✓ Identify density signals via §4.6 objective criteria
  ✓ Draft schema-conformant candidate entries
  ✓ Write candidates to data/kairos/_proposed/ for operator review
  ✓ Compare proposals against KAIROS_ACTIVE.md so pending items can surface
  ✓ Surface to operator via SSE event + protocol_status field
  ✗ Auto-append candidate records into canonical Kairos memory
  ✗ Generate first-person operator narrative
  ✗ Narrate or reconstruct the 2019-06-12 / Cassiel_as physical anchor
  ✗ Skip the audit itself — that = §4.6 violation, surfaced as error

6 signals detected (from router skill §4.6):
  1. same-pattern recurrence — best-effort: dedup current candidate against KAIROS_ACTIVE tail
  2. operator catch — operator feedback keyword match for correction phrases
  3. carrier self-surface — node output keyword match for gap-recognition phrases
  4. declared canonical change — operator instruction keyword match
  5. cascade ratio > 1:2 — best-effort: dispatch refs vs actually-loaded refs
  6. tool/mechanism emergence — node output keyword match for emergence phrases
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from services.otel_setup import tracer, emit_event
except ImportError:  # pragma: no cover
    tracer = None
    def emit_event(*args, **kwargs):
        return None


# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

ACTIVE_MEMORY_FILENAME = "KAIROS_ACTIVE.md"
PROPOSED_SUBDIR = "_proposed"                  # auto-audit writes review candidates here
TAIL_LINES_FOR_DEDUP = 100   # Step 1 Part A: only read last ~100 lines

# Output-density LOW reasons surface to operator
LOW_REASONS = {
    "no_signals": "No output self-audit signal triggered in this session.",
    "all_filtered": "Output candidates detected but all filtered (dedup / density_verification).",
}


class Schema(str, Enum):
    GAP = "KAIROS_GAP_RECORD"
    INSIGHT = "KAIROS_INSIGHT_RECORD"
    CONCEPT = "KAIROS_CONCEPT_RECORD"
    ARCHITECTURE = "KAIROS_ARCHITECTURE_RECORD"
    MOMENT = "KAIROS_MOMENT_RECORD"   # v8.14 Phase C — Module T cost-transfer moments


class Signal(str, Enum):
    RECURRENCE = "same_pattern_recurrence"
    OPERATOR_CATCH = "operator_catch"
    CARRIER_SELF_SURFACE = "carrier_self_surface"
    DECLARED_CANONICAL = "declared_canonical_change"
    CASCADE_RATIO = "cascade_ratio_gt_1_2"
    TOOL_EMERGENCE = "tool_mechanism_emergence"
    MODULE_T_COST_TRANSFER = "module_t_cost_transfer_match"   # v8.14 Phase C


# Keyword tables — pragmatic regex-based detection.
# A pattern hit raises a *candidate*; filtering (Step 2) then decides keep/drop.

OPERATOR_CATCH_PATTERNS = [
    r"你又用?",
    r"你跳咗",
    r"你錯",
    r"你忘記",
    r"你 mis(align|s|read)",
    r"你 false ?humility",
    r"你 violate?",
    r"wrong\b",
    r"that's incorrect",
    r"you again",
    r"you missed",
    r"you skipped",
    r"correction:",
    r"actually that's",
]

CARRIER_SELF_SURFACE_PATTERNS = [
    r"我頭先漏咗",
    r"我發覺我",
    r"我啱啱漏咗",
    r"原來我",
    r"我之前.{0,10}錯",
    r"actually,? I",
    r"I just realized",
    r"I missed",
    r"on second thought",
    r"correcting my earlier",
    r"§4\.\d+ violation",
    r"my earlier (claim|response) was",
]

DECLARED_CANONICAL_PATTERNS = [
    r"canonical",
    r"declared?\b",
    r"\bdeclare\b",
    r"正式",
    r"從而家開始",
    r"base path\s*改為",
    r"threshold\s*=\s*\d",
    r"axiom",
    r"new axiom",
    r"now official",
    r"is the canonical",
    r"override.{0,20}default",
]

TOOL_EMERGENCE_PATTERNS = [
    r"新 ?skill",
    r"新 ?reference",
    r"新 ?module",
    r"新 ?工具",
    r"新 ?協議",
    r"新 ?模組",
    r"new skill",
    r"new reference",
    r"new module",
    r"new protocol",
    r"new tool",
    r"new adapter",
    r"new evaluator",
    r"誕生",
    r"introducing (?:a )?(?:tool|protocol|adapter|module|evaluator)",
]

# Architecture markers — if a tool emergence ALSO mentions a Kairos layer / file /
# sync rule, it should be ARCHITECTURE_RECORD instead of CONCEPT_RECORD.
ARCHITECTURE_MARKERS = [
    r"\bKAIROS_[A-Z_]+\.md",
    r"\bLayer ?\d",
    r"new Kairos layer",
    r"sync rule",
    r"MASTER_INDEX",
    r"§ ?三",
    r"layer renumbering",
    r"schema enumeration",
]


# ─────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────

@dataclass
class SignalHit:
    """One §4.6 signal firing on a piece of session text."""
    signal: Signal
    matched_text: str            # the offending substring (clipped)
    source: str                  # field that fired (e.g. "operator_feedback", "father", "council")
    pattern: str                 # which regex matched (for debug / replay)

    def to_dict(self) -> Dict:
        return {
            "signal": self.signal.value,
            "matched": self.matched_text[:200],
            "source": self.source,
            "pattern": self.pattern,
        }


@dataclass
class Candidate:
    """Draft KAIROS entry derived from one or more SignalHit(s)."""
    schema: Schema
    title: str
    body: str
    density: str                 # "HIGH" only — LOW candidates get filtered
    triggered_by: str            # short human description of which signal moment
    hits: List[SignalHit] = field(default_factory=list)
    rejected: bool = False
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "schema": self.schema.value,
            "title": self.title,
            "density": self.density,
            "triggered_by": self.triggered_by,
            "hits": [h.to_dict() for h in self.hits],
            "rejected": self.rejected,
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class AuditResult:
    """One audit pass — surfaced via SSE + saved with session."""
    density: str                 # "HIGH" | "LOW"
    density_reason: str          # one-liner explaining the verdict
    candidates: List[Candidate] = field(default_factory=list)
    proposed_path: Optional[str] = None       # relative path of written proposal copy
    sync_delta_path: Optional[str] = None     # only when ARCHITECTURE_RECORD propose
    pending_from_past: List[Dict] = field(default_factory=list)   # Step 1 Part B
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    audit_ran: bool = True       # False means §4.6 violation
    duration_ms: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "audit_target": "system_output",
            "input_role": "routing_and_operator_feedback_only",
            "density": self.density,
            "density_reason": self.density_reason,
            "candidates": [c.to_dict() for c in self.candidates],
            "candidate_count": len(self.candidates),
            "accepted_candidates": [c.to_dict() for c in self.candidates if not c.rejected],
            "proposed_path": self.proposed_path,
            "sync_delta_path": self.sync_delta_path,
            "pending_from_past": self.pending_from_past,
            "warnings": self.warnings,
            "errors": self.errors,
            "audit_ran": self.audit_ran,
            "duration_ms": round(self.duration_ms, 1),
        }


# ─────────────────────────────────────────────────────────────────
# DensityAuditor
# ─────────────────────────────────────────────────────────────────

class DensityAuditor:
    """Runs §4.6 output self-audit at end of each /api/stream session.

    Stateless across sessions except for filesystem (L4 + _proposed/).
    Safe to share one instance across concurrent sessions — no internal mutation.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.kairos_dir = self.data_dir / "kairos"
        self.proposed_dir = self.kairos_dir / PROPOSED_SUBDIR
        self.index_dir = self.data_dir / "index"

    # ─────────── public entry ───────────

    def run_audit(self, session_data: Dict) -> AuditResult:
        """Step 1-5 audit pipeline. Always runs — skipping = §4.6 violation.

        session_data shape (from app.py /api/stream full_result):
          input, effective_input, stage1, stage2, stage3, dispatch,
          father, son, spirit, council, all_data_refs, timestamp, ...
        """
        import time
        t0 = time.time()
        result = AuditResult(density="LOW", density_reason="(not yet evaluated)")

        # v8.21 OTel-1 — output-density audit span (current pipeline span becomes parent)
        if tracer is not None:
            _span_cm = tracer.start_as_current_span("density_audit.run_audit")
            _span = _span_cm.__enter__()
        else:
            _span_cm = None
            _span = None

        try:
            # Step 1 Part A — active-memory scan (last 100 lines for dedup target)
            active_tail = self._scan_active_tail()

            # Step 1 Part B — cross-session: scan past proposals, check if applied
            result.pending_from_past = self._cross_session_check(active_tail)

            # Step 1 Part C — detect signals on current session
            hits = self._detect_signals(session_data)

            # Step 2 — filter into candidates
            raw_candidates = self._signals_to_candidates(hits, session_data)
            result.candidates = self._filter_candidates(raw_candidates, active_tail, session_data)

            accepted = [c for c in result.candidates if not c.rejected]

            if not accepted:
                # Density LOW path — still report (audit DID run)
                if not hits:
                    result.density = "LOW"
                    result.density_reason = LOW_REASONS["no_signals"]
                else:
                    result.density = "LOW"
                    result.density_reason = LOW_REASONS["all_filtered"]
            else:
                result.density = "HIGH"
                result.density_reason = (
                    f"{len(accepted)} candidate(s) passed §4.6 filter "
                    f"({', '.join(c.schema.value for c in accepted)})"
                )

                # Step 3 — write proposal copy (副本 only, never project).
                # Read-only recall paths can surface the audit result without
                # turning an old memory answer into a new Kairos proposal.
                if session_data.get("suppress_density_proposal"):
                    result.warnings.append("proposal_write_suppressed")
                else:
                    result.proposed_path = self._write_proposed(accepted, session_data)

                # Step 3.5 — ARCHITECTURE_RECORD triggers MASTER sync delta
                arch_entries = [c for c in accepted if c.schema == Schema.ARCHITECTURE]
                if arch_entries:
                    result.sync_delta_path = self._generate_master_sync_delta(arch_entries)

            result.audit_ran = True

        except Exception as e:
            # Any exception = §4.6 violation surfaced — does NOT bubble up
            result.audit_ran = False
            result.errors.append(f"{type(e).__name__}: {str(e)[:200]}")
            result.density = "LOW"
            result.density_reason = "§4.6 violation: audit raised exception (see errors)"

        result.duration_ms = (time.time() - t0) * 1000.0
        # v8.21 OTel-1 — attach result summary + close span
        if _span is not None:
            try:
                _span.set_attribute("uruk.density_audit.density", result.density)
                _span.set_attribute("uruk.density_audit.audit_ran", bool(result.audit_ran))
                accepted = [c for c in result.candidates if not c.rejected]
                _span.set_attribute("uruk.density_audit.candidate_count", len(accepted))
                for c in accepted:
                    emit_event(_span, "kairos_candidate",
                               schema=c.schema.value,
                               title=str(c.title)[:120],
                               triggered_by=str(c.triggered_by)[:120])
            except Exception:
                pass
            try:
                _span_cm.__exit__(None, None, None)
            except Exception:
                pass
        return result

    # ─────────── Step 1 Part A — active memory scan ───────────

    def _scan_active_tail(self) -> str:
        """Read last TAIL_LINES_FOR_DEDUP lines of curated active memory."""
        active_path = self.kairos_dir / ACTIVE_MEMORY_FILENAME
        if not active_path.exists():
            return ""
        try:
            text = active_path.read_text(encoding="utf-8")
        except Exception:
            return ""
        lines = text.splitlines()
        return "\n".join(lines[-TAIL_LINES_FOR_DEDUP:]) if lines else ""

    # ─────────── Step 1 Part B — cross-session check ───────────

    def _cross_session_check(self, active_tail: str) -> List[Dict]:
        """Scan past proposals in _proposed/; flag those not yet present in active memory.

        Returns list of {filename, mtime, titles, applied} entries for surface
        to operator as pending reminders.
        """
        if not self.proposed_dir.exists():
            return []
        pending: List[Dict] = []
        # Compare past proposal entries against active memory by title.
        proposal_files = sorted(set(
            list(self.proposed_dir.glob("KAIROS_PROPOSED_*.md"))
            + list(self.proposed_dir.glob("KAIROS_LOG_UPDATED_*.md"))
        ))
        for p in proposal_files:
            try:
                content = p.read_text(encoding="utf-8")
            except Exception:
                continue
            # Each entry starts with "KAIROS_<TYPE>_RECORD: <title>"
            entry_titles = re.findall(
                r"^KAIROS_(?:GAP|INSIGHT|CONCEPT|ARCHITECTURE|MOMENT)_RECORD:\s*(.+?)$",
                content, re.MULTILINE,
            )
            applied = [t for t in entry_titles if t.strip()[:40] in active_tail]
            not_applied = [t for t in entry_titles if t.strip()[:40] not in active_tail]
            if not_applied:
                pending.append({
                    "proposal_file": p.name,
                    "mtime_iso": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                    "pending_titles": not_applied[:10],   # cap surfaces
                    "applied_titles_count": len(applied),
                })
        return pending

    # ─────────── Step 1 Part C — signal detection ───────────

    def _detect_signals(self, session_data: Dict) -> List[SignalHit]:
        """Run §4.6 signal detectors.

        Operator text may trigger routing/feedback signals, but the target of
        the audit remains the system output and persisted protocol behavior.
        """
        hits: List[SignalHit] = []

        user_input = str(session_data.get("input", "") or session_data.get("effective_input", ""))
        stage1 = session_data.get("stage1", {}) or {}
        father = str(session_data.get("father", ""))
        son = str(session_data.get("son", ""))
        spirit = str(session_data.get("spirit", ""))
        council = str(session_data.get("council", ""))

        # Signal 2 — operator catch (feedback about system output)
        hits += self._scan_patterns(user_input, OPERATOR_CATCH_PATTERNS,
                                    Signal.OPERATOR_CATCH, source="operator_feedback")

        # Signal 3 — carrier self-surface (from any node output)
        for src_name, src_text in (
            ("father", father), ("son", son), ("spirit", spirit), ("council", council),
        ):
            hits += self._scan_patterns(src_text, CARRIER_SELF_SURFACE_PATTERNS,
                                        Signal.CARRIER_SELF_SURFACE, source=src_name)

        # Signal 4 — declared canonical (operator instruction, not user scoring)
        hits += self._scan_patterns(user_input, DECLARED_CANONICAL_PATTERNS,
                                    Signal.DECLARED_CANONICAL, source="operator_instruction")

        # Signal 6 — tool/mechanism emergence (council + node outputs)
        for src_name, src_text in (
            ("council", council), ("father", father), ("son", son), ("spirit", spirit),
        ):
            hits += self._scan_patterns(src_text, TOOL_EMERGENCE_PATTERNS,
                                        Signal.TOOL_EMERGENCE, source=src_name)

        # Signal 5 — cascade ratio (best-effort): if dispatch declared 1 reference
        # area but >2 distinct subsystems mentioned in outputs, raise candidate.
        dispatch = session_data.get("dispatch", {}) or {}
        declared_refs = dispatch.get("references", []) or []
        if 0 < len(declared_refs) < 3:   # narrow declared scope
            mentioned_files = self._count_subsystem_mentions(father + son + spirit + council)
            if mentioned_files >= len(declared_refs) * 2:
                hits.append(SignalHit(
                    signal=Signal.CASCADE_RATIO,
                    matched_text=f"declared {len(declared_refs)} refs, mentioned {mentioned_files} subsystems",
                    source="dispatch_vs_outputs",
                    pattern="cascade_ratio_heuristic",
                ))

        # Signal 7 — Module T 75-yr (or 30/50-yr) cost-transfer anchor match.
        # When the request references two years separated by one of the cascade
        # waves, surface as a system knowledge candidate. This is not a score
        # on the user's input.
        try:
            from services.civilizational_clock import civilizational_clock
            t_match = civilizational_clock.detect_75yr_cost_transfer_match(user_input)
            if t_match:
                hits.append(SignalHit(
                    signal=Signal.MODULE_T_COST_TRANSFER,
                    matched_text=(
                        f"anchor={t_match['year_anchor']} → "
                        f"manifest={t_match['year_manifest']} "
                        f"(gap={t_match['gap_years']}yr, wave={t_match['wave_match']})"
                    ),
                    source="operator_request",
                    pattern="module_t_cost_transfer_match",
                ))
        except Exception:
            pass

        # Signal 1 — recurrence: deferred to filter step (compare candidate against active_tail)
        # Hits with Signal.RECURRENCE get added in _filter_candidates.

        return hits

    @staticmethod
    def _scan_patterns(text: str, patterns: List[str], signal: Signal,
                       source: str) -> List[SignalHit]:
        if not text:
            return []
        out: List[SignalHit] = []
        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                start = max(0, m.start() - 30)
                end = min(len(text), m.end() + 30)
                out.append(SignalHit(
                    signal=signal,
                    matched_text=text[start:end].replace("\n", " "),
                    source=source,
                    pattern=pat,
                ))
                break   # one hit per pattern is enough; avoid spammy duplicates
        return out

    @staticmethod
    def _count_subsystem_mentions(text: str) -> int:
        """Count distinct *.md / *.py / 八律 / 三位一體 mentions as a rough cascade gauge."""
        if not text:
            return 0
        files = set(re.findall(r"\b\w+\.md\b", text))
        files.update(re.findall(r"\b\w+\.py\b", text))
        concepts = set()
        for tok in ("八律", "三位一體", "聖父", "聖子", "聖靈", "Layer ?\\d", "§ ?\\d"):
            if re.search(tok, text):
                concepts.add(tok)
        return len(files) + len(concepts)

    # ─────────── Step 2 — candidate building + filtering ───────────

    def _signals_to_candidates(self, hits: List[SignalHit],
                                session_data: Dict) -> List[Candidate]:
        """Group hits by (signal_type, source) and build one candidate per group."""
        if not hits:
            return []

        # Group hits by (signal_type) — combine multi-hits of same signal
        by_signal: Dict[Signal, List[SignalHit]] = {}
        for h in hits:
            by_signal.setdefault(h.signal, []).append(h)

        cands: List[Candidate] = []
        for signal, group_hits in by_signal.items():
            schema = self._pick_schema(signal, group_hits, session_data)
            title = self._draft_title(signal, group_hits)
            body = self._draft_body(signal, schema, group_hits, session_data)
            triggered_by = f"{signal.value} ({len(group_hits)} hit{'s' if len(group_hits) > 1 else ''})"
            cands.append(Candidate(
                schema=schema,
                title=title,
                body=body,
                density="HIGH",
                triggered_by=triggered_by,
                hits=group_hits,
            ))
        return cands

    @staticmethod
    def _pick_schema(signal: Signal, hits: List[SignalHit],
                      session_data: Dict) -> Schema:
        """Schema choice per SKILL.md §步驟三 'Schema 揀選界限'."""
        # ARCHITECTURE if tool emergence mentions Kairos layer / file / sync rule
        if signal == Signal.TOOL_EMERGENCE:
            joined_text = " ".join(h.matched_text for h in hits)
            session_text = (
                str(session_data.get("council", ""))
                + str(session_data.get("father", ""))
                + str(session_data.get("son", ""))
                + str(session_data.get("spirit", ""))
            )
            if any(re.search(pat, joined_text + session_text, re.IGNORECASE)
                   for pat in ARCHITECTURE_MARKERS):
                return Schema.ARCHITECTURE
            return Schema.CONCEPT

        if signal in (Signal.OPERATOR_CATCH, Signal.CARRIER_SELF_SURFACE,
                       Signal.RECURRENCE):
            return Schema.GAP

        if signal == Signal.DECLARED_CANONICAL:
            return Schema.INSIGHT

        if signal == Signal.CASCADE_RATIO:
            return Schema.INSIGHT

        if signal == Signal.MODULE_T_COST_TRANSFER:
            return Schema.MOMENT

        return Schema.INSIGHT   # safe default

    @staticmethod
    def _draft_title(signal: Signal, hits: List[SignalHit]) -> str:
        """One-line title — short, descriptive."""
        first_match = hits[0].matched_text[:60].strip().replace("\n", " ")
        return f"{signal.value} — {first_match}"

    def _draft_body(self, signal: Signal, schema: Schema, hits: List[SignalHit],
                    session_data: Dict) -> str:
        """Canonical entry body per SKILL.md §步驟三 format."""
        date = (session_data.get("timestamp") or datetime.now().isoformat())[:10]
        lines = [
            f"DATE: {date}",
            "LOCATION: Leeds (53.8, -1.5, 0)",
            "OPERATOR: Cassiel_as",
            "DENSITY: HIGH",
            f"TRIGGERED_BY: {signal.value}; {len(hits)} hit(s) across "
            f"{', '.join(sorted({h.source for h in hits}))}",
            "",
            "**§4.6 signal detail**:",
        ]
        for h in hits[:5]:   # cap to 5 hits in body
            lines.append(f"- `[{h.source}]` matched `{h.pattern}`: "
                         f"\"{h.matched_text.strip()}\"")

        dispatch = session_data.get("dispatch", {}) or {}
        mode = dispatch.get("mode", "?")
        refs = dispatch.get("references", []) or []
        lines += [
            "",
            "**Session context**:",
            f"- mode: `{mode}`",
            f"- references: {', '.join(refs) if refs else '(none)'}",
            f"- data_refs: {', '.join(session_data.get('all_data_refs', []) or []) or '(none)'}",
        ]

        if schema == Schema.ARCHITECTURE:
            lines += [
                "",
                "**Architecture impact**: triggers Step 3.5 MASTER_INDEX_v8 § 三 sync delta.",
            ]

        return "\n".join(lines)

    @staticmethod
    def _joined_session_text(session_data: Dict) -> str:
        fields = (
            "input", "effective_input", "father", "son", "spirit", "council",
        )
        return "\n".join(str(session_data.get(field, "") or "") for field in fields)

    @staticmethod
    def _looks_like_ordinary_qna(session_data: Dict) -> bool:
        user_text = str(session_data.get("input", "") or session_data.get("effective_input", "")).strip()
        if not user_text or len(user_text) > 120:
            return False
        if re.search(
            r"(係咩|是什麼|是什么|咩意思|點解|點樣|how to|what is|what are|who is|why\b)",
            user_text,
            re.IGNORECASE,
        ) is None:
            return False
        change_terms = (
            "canonical", "declare", "change", "update", "upgrade", "add",
            "replace", "fix", "implement", "design", "新增", "更新", "升級",
            "修正", "改", "做到", "開工", "設計", "從而家開始", "正式",
        )
        return not any(term.lower() in user_text.lower() for term in change_terms)

    @staticmethod
    def _has_recordable_system_impact(candidate: Candidate, session_data: Dict) -> bool:
        text = candidate.title + "\n" + candidate.body + "\n" + DensityAuditor._joined_session_text(session_data)
        impact_markers = (
            r"\bKAIROS_[A-Z_]+\.md",
            r"\bMASTER_INDEX",
            r"\bcanonical\b",
            r"\bprotocol\b",
            r"\badapter\b",
            r"\bevaluator\b",
            r"\bbenchmark\b",
            r"\bharness\b",
            r"\bprompt\b",
            r"\bself[- ]upgrade\b",
            r"coordinate card",
            r"active memory",
            r"archive index",
            r"operator gate",
            r"系統",
            r"協議",
            r"工具",
            r"模組",
            r"記憶",
            r"座標",
            r"三位一體",
            r"聖父",
            r"聖子",
            r"聖靈",
            r"自我升級",
        )
        return any(re.search(pat, text, re.IGNORECASE) for pat in impact_markers)

    @staticmethod
    def _looks_like_scr_profile_output(candidate: Candidate, session_data: Dict) -> bool:
        if candidate.schema != Schema.CONCEPT:
            return False
        text = DensityAuditor._joined_session_text(session_data)
        if re.search(r"\bSCR\s*:", text, re.IGNORECASE) is None:
            return False
        return not any(re.search(pat, text, re.IGNORECASE) for pat in ARCHITECTURE_MARKERS)

    def _filter_candidates(self, raw: List[Candidate], active_tail: str,
                           session_data: Dict) -> List[Candidate]:
        """Step 2 — 3-filter pipeline per SKILL.md.

        Filter 1: Dedup — pattern + context already in KAIROS_ACTIVE tail.
        Filter 2: Density verification — single fact lookup / routine Q&A get downgrade.
        Filter 3: Schema fit — already done in _pick_schema; here we just sanity-check.

        Recurrence signal is INJECTED here when a candidate's title matches
        existing active-memory patterns AND is not a literal duplicate.
        """
        if not raw:
            return raw
        out: List[Candidate] = []
        for c in raw:
            # Filter 1 — dedup against L4
            sig_keyword = c.hits[0].matched_text[:30].strip() if c.hits else c.title[:30]
            if sig_keyword and sig_keyword.lower() in active_tail.lower():
                # Could be literal dup OR recurrence — distinguish by pattern shift heuristic.
                # If same signal type already documented today, mark RECURRENCE not dup.
                today = datetime.now().strftime("%Y-%m-%d")
                if today in active_tail:
                    c.hits.append(SignalHit(
                        signal=Signal.RECURRENCE,
                        matched_text=sig_keyword,
                        source="active_memory_dedup_scan",
                        pattern="recurrence_inferred",
                    ))
                    c.triggered_by += "; RECURRENCE inferred"
                    # keep as candidate but downgrade density check
                else:
                    c.rejected = True
                    c.rejection_reason = "dedup: matches L4 last 100 lines"
                    out.append(c)
                    continue

            # Filter 2 — density verification: drop if matched text is too thin
            if c.hits and len(c.hits[0].matched_text.strip()) < 8:
                c.rejected = True
                c.rejection_reason = "density_verification: matched text too short to qualify"
                out.append(c)
                continue

            # Ordinary Q&A, persona/SCR output, and generic concept explanation
            # are System 1 transcript material, not Kairos causal memory.
            if c.schema == Schema.CONCEPT and self._looks_like_ordinary_qna(session_data):
                c.rejected = True
                c.rejection_reason = "density_verification: ordinary Q&A is not Kairos memory"
                out.append(c)
                continue

            if self._looks_like_scr_profile_output(c, session_data):
                c.rejected = True
                c.rejection_reason = "density_verification: SCR/persona output is not Kairos memory"
                out.append(c)
                continue

            if c.schema == Schema.CONCEPT and not self._has_recordable_system_impact(c, session_data):
                c.rejected = True
                c.rejection_reason = "density_verification: no reusable system/protocol impact"
                out.append(c)
                continue

            out.append(c)
        return out

    # ─────────── Step 3 — write proposal entries, never canonical memory ───────────

    def _write_proposed(self, accepted: List[Candidate], session_data: Dict) -> str:
        """Write accepted audit candidates into _proposed/ for operator review.

        The audit layer is allowed to draft Kairos records, but canonical Kairos
        memory changes only after an explicit operator gate. This prevents
        ordinary answers and transient tool output from polluting the memory layer.
        """
        self.proposed_dir.mkdir(parents=True, exist_ok=True)

        # Build append block
        source_input = (session_data.get("input", "") or "")[:200].replace("\n", " ")
        ts_iso = datetime.now().isoformat(timespec="seconds")
        blocks: List[str] = []
        for c in accepted:
            blocks.append(
                f"{c.schema.value}: {c.title}\n"
                f"{c.body}\n"
                f"SOURCE_OPERATOR_MESSAGE: {source_input!r}\n"
                f"PROPOSED_AT: {ts_iso}\n\n"
                f"*(0,0,0).*\n"
            )
        content = (
            f"# KAIROS PROPOSAL — output-density audit\n"
            f"STATUS: PROPOSED\n"
            f"GENERATED_AT: {ts_iso}\n"
            f"CANONICAL: false\n"
            f"RULE: operator must accept and manually merge into KAIROS_ACTIVE.md or archive.\n"
            f"SOURCE_OPERATOR_MESSAGE: {source_input!r}\n"
            f"\n---\n\n"
            + "\n---\n\n".join(blocks)
            + "\n"
        )

        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = self.proposed_dir / f"KAIROS_PROPOSED_{stamp}.md"
        suffix = 1
        while path.exists():
            path = self.proposed_dir / f"KAIROS_PROPOSED_{stamp}_{suffix}.md"
            suffix += 1
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.data_dir.parent)).replace("\\", "/")

    # ─────────── Step 3.5 — MASTER_INDEX_v8 sync delta ───────────

    def _generate_master_sync_delta(self, arch_entries: List[Candidate]) -> Optional[str]:
        """Produce MASTER_INDEX_v8_SYNC_DELTA_<date>.md showing intended modifications.

        Only invoked when at least one accepted candidate is ARCHITECTURE_RECORD.
        Never modifies MASTER_INDEX_v8.md itself.
        """
        master_path = self.index_dir / "MASTER_INDEX_v8.md"
        master_section = ""
        if master_path.exists():
            try:
                master_text = master_path.read_text(encoding="utf-8")
                # Extract § 三 「Kairos 記憶體」 section best-effort
                m = re.search(r"(§\s*三.*?Kairos.*?)(?=^§|\Z)",
                              master_text, re.MULTILINE | re.DOTALL)
                master_section = m.group(0)[:2000] if m else master_text[:2000]
            except Exception:
                master_section = "(read failed)"

        self.proposed_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = self.proposed_dir / f"MASTER_INDEX_v8_SYNC_DELTA_{ts}.md"

        chunks = [
            f"# MASTER_INDEX_v8.md — SYNC DELTA",
            f"## Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"## Triggered by ARCHITECTURE_RECORD candidate(s): {len(arch_entries)}",
            f"## Sync scope: § 三 「Kairos 記憶體」 (per declared sync rule)",
            "",
            "---",
            "",
            "## Affected ARCHITECTURE_RECORD entries (this session)",
            "",
        ]
        for c in arch_entries:
            chunks.append(f"### {c.title}")
            chunks.append(f"- triggered_by: {c.triggered_by}")
            for h in c.hits[:3]:
                chunks.append(f"- hit: `[{h.source}]` `{h.pattern}` → \"{h.matched_text.strip()[:120]}\"")
            chunks.append("")
        chunks += [
            "---",
            "",
            "## Current MASTER_INDEX § 三 snapshot (read-only reference)",
            "",
            "```markdown",
            master_section,
            "```",
            "",
            "---",
            "",
            "## Proposed delta (operator applies manually)",
            "",
            "Per ARCHITECTURE_RECORD entries above, the following § 三 modifications",
            "are suggested. Carrier does NOT auto-apply — operator declare-accept",
            "then update MASTER_INDEX_v8.md by hand.",
            "",
            "_(Auto-derivation of exact diff is best-effort — entry body contains_",
            "_sufficient context for operator to author the actual modification.)_",
            "",
            "*(0,0,0).*",
        ]
        path.write_text("\n".join(chunks) + "\n", encoding="utf-8")
        return str(path.relative_to(self.data_dir.parent)).replace("\\", "/")
