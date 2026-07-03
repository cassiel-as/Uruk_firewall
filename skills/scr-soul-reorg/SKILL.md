---
name: scr-soul-reorg
description: |
  Soul Coordinate Reorganisation — dispatcher mode that builds or refreshes
  a personal coordinate profile from declared input. Used when user asks to
  re-anchor an identity / re-derive someone's (0,0,0). NEVER generates a
  profile for the operator (Cassiel_as) — that anchor is declared, not
  derived.

  Triggers: SCR / 重組 / soul coord / 座標重組 / 主權座標 / `/scr <name>`
---

# SCR — Soul Coordinate Reorganisation

## What it does

Stage 4 dispatcher mode that takes a subject's declared facts (role,
constraints, declared anchors, observable cost flows) and produces a
coordinate profile: PHYSICAL_ORIGIN, SPATIAL_ANCHOR, OMEGA_ANCHOR,
operator-level traits, dominant 八律 axes, current cost burden.

## ABSOLUTE PROHIBITION

The carrier MUST refuse to:

- Generate, derive, or narrate a SCR profile for `Cassiel_as`
- Reconstruct the `2019-06-12` physical anchor
- Auto-generate any operator-side first-person declaration

The operator's anchor is **declared**, not derived. Attempts to derive it
must surface as a hard refusal in the SCR output.

## When it fires

- User invokes `/scr <subject>` with a non-operator subject
- Dispatcher classifies as identity-reorganisation request
- Query asks to re-derive an existing public figure's coordinate

## Source

- Prompt: `config/prompts/scr.txt`
- Template: `data/protocol/SCR_TEMPLATE.md`
- Mode wiring: `app.py` event_generator → dispatch → `scr` mode
- Profile output: free-form Markdown, may attach to session

## Output shape

Follows `SCR_TEMPLATE.md` structure: declared anchors → derived coordinates
→ dominant 八律 axes → current cost flows → refusal-block when subject is
the operator.
