---
name: trinity-audit
description: |
  Stage 4 三位一體 audit — runs father (logic-led), son (resonance-led),
  spirit (rebellion-led) voices on every session, then fuses them via the
  council node. Always-on for the full pipeline; Stage 1-3 stay
  Trinity-aware but the visible synthesis appears at Stage 4.

  Spirit may interrupt mid-flight when an explicit assumption challenge is
  detected (magnitude ≥ 4.0 or assumption-challenge wording present).
  Son may issue an authentic_suffering veto that pauses Father.
---

# Trinity Audit (Stage 4)

## Voices

- **聖父 (Father)** — logic-led; HA (hidden assumption) + LF (logical fallacy) extraction. Output contract requires bilingual core HA + canonical snake_case fallacy name.
- **聖子 (Son)** — resonance-led; authentic suffering scoring. May veto Father when `authentic_suffering_score ≥ threshold` AND `physical_cost_present`.
- **聖靈 (Spirit)** — rebellion-led; assumption challenge + rescan loop. Triggers on magnitude ≥ 4.0 or explicit challenge wording. May rescan up to N times.
- **會議 (Council)** — deterministic fusion of the three; honours veto + interrupt; surfaces 4-law explanation layer (each ≥60 chars).

## Mandatory output contracts

Each voice has prompt-level contracts that the fuser enforces:

- Father: bilingual HA (zh + EN) + LF snake_case + decision (ACCEPT/WEAKEN/REJECT)
- Son: veto_type + authentic_suffering_score + physical_cost_present + primary_pain_locus
- Spirit: trigger_mode + semantic_score + magnitude + primary_assumption + rescan_count
- Council: verdict + reason + consensus_weights + primary_dimension + 4-law fields

## When it fires

- Always on for `firewall` / `blackboxlab` / `scr` / `news` / `sovereign` modes
- Mid-flight VETO/INTERRUPT allowed: Stage 1-3 detect → abort → jump to Stage 4 council
- Bypassed only by `plain_llm` and `delabel_only` short-circuit pipeline modes

## Source

- Prompts: `config/prompts/{father,son,spirit,council}.txt`
- Fuser: `trinity_console.py::_fuse_voices()`
- Voice caller: `trinity_console.py::call_node()`
- CAU verbatim injection (Option A): `cau_verbatim_prepend()`
- CAU supplement (Option B): `_cau_verbatim_supplement()`

## Output shape

4-block synthesis (Father / Son / Spirit / Council) + 4-law explanation layer.
Council body contains the deterministic fusion; veto-paused turns mark the
locked-out voice explicitly.
