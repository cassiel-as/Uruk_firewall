---
name: kairos-density-audit
description: |
  §4.6 runtime audit that fires after every pipeline session to detect
  high-density Kairos moments and draft schema-conformant proposal entries
  under data/kairos/_proposed/. Triggered automatically — skipping = §4.6
  violation.

  Triggers on six pattern families: same-pattern recurrence, operator catch,
  carrier self-surface, declared canonical change, cascade ratio > 1:2, and
  tool/mechanism emergence. Also detects Module T 75-year cost-transfer
  anchor matches.
---

# Kairos Density Audit (§4.6 runtime)

## What it does

Runs after every `/api/stream` session. Scans session text (operator routing
input + the four voices + council) for §4.6 density signals. When signals fire,
drafts `KAIROS_<TYPE>_RECORD` proposal entries into
`data/kairos/_proposed/KAIROS_PROPOSED_*.md`.

It never auto-appends to canonical Kairos memory. Operator review is required
before a compact record can be merged into `data/kairos/KAIROS_ACTIVE.md` or a
query-only archive.

## Signals detected

1. `same_pattern_recurrence` — title overlap with last 100 lines of `KAIROS_ACTIVE.md`
2. `operator_catch` — corrective phrasing in user input ("你又用咗", "wrong", etc.)
3. `carrier_self_surface` — node output recognising its own gap
4. `declared_canonical_change` — declaration phrasing ("canonical", "axiom", etc.)
5. `cascade_ratio_gt_1_2` — dispatch declared N refs but >2N subsystems mentioned
6. `tool_mechanism_emergence` — explicit emergence of a reusable tool/protocol
7. `module_t_cost_transfer_match` — 75/30/50-yr anchor pair in input

## Schema types

| Schema | When |
|---|---|
| `KAIROS_GAP_RECORD` | operator_catch / carrier_self_surface / recurrence |
| `KAIROS_INSIGHT_RECORD` | declared_canonical / cascade_ratio / default |
| `KAIROS_CONCEPT_RECORD` | tool_emergence without architecture markers |
| `KAIROS_ARCHITECTURE_RECORD` | tool_emergence with KAIROS_*.md / Layer-N / sync rule markers |
| `KAIROS_MOMENT_RECORD` | module_t_cost_transfer_match |

## Carrier boundary

- ✓ Detect signals, draft proposal entries, surface via SSE
- ✓ Compare past proposals against `KAIROS_ACTIVE.md` so pending items can surface
- ✗ Auto-append into `KAIROS_ACTIVE.md` or historical logs
- ✗ Generate first-person operator narrative
- ✗ Narrate or reconstruct the 2019-06-12 / Cassiel_as physical anchor
- ✗ Skip the audit (skipping = §4.6 violation, surfaced as error in `density_audit` event)

## Source

- Implementation: `density_audit.py`
- Runtime entry: `console.run_density_audit(session_data)` → `app.py` `audit_and_finalize`
- Active memory: `data/kairos/KAIROS_ACTIVE.md`
- Proposal queue: `data/kairos/_proposed/KAIROS_PROPOSED_*.md`
- Archives: `data/kairos/KAIROS_LOG_MIDDLE.md`, `data/kairos/KAIROS_LOG_UPDATED_v8.md`
- Related: `KAIROS_CORE.md`, `KAIROS_ARCHIVE_INDEX.md`
