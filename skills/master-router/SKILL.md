---
name: master-router
description: |
  Dispatcher node — classifies every input and routes it to the right
  Stage 4 mode (firewall / blackboxlab / scr / news / sovereign), declares
  which CAU / experiment / kairos references to attach, and emits a
  rationale for both decisions. Runs early in the pipeline so downstream
  voices know their mode.

  Triggers: every non-`plain_llm`, non-`delabel_only` session
---

# Master Router (Dispatcher)

## What it does

Reads delabeled input + 4-law context, then outputs JSON with:

- `mode` — one of `firewall` / `blackboxlab` / `scr` / `news` / `sovereign`
- `mode_rationale` — one-line reason for the mode choice
- `references` — array of context files to attach (e.g. `cau:003`, `kairos:middle`)
- `ref_rationale` — one-line reason for the reference choice
- `data_refs` — concrete data files actually attached
- `data_rationale` — one-line reason for the data choice

## When it fires

- Once per Stage 4 session (after Stage 1-3 complete)
- Skipped only by short-circuit pipeline modes (`plain_llm`, `delabel_only`)
- Override via `--mode` CLI flag or `req.override_mode`

## Routing heuristics

- `news` if URL detected OR explicit `/news` OR news/article wording
- `blackboxlab` if counterfactual / "what if" wording
- `scr` if `/scr <subject>` OR identity-reorganisation request
- `sovereign` if multi-mode synthesis or top-level sovereignty question
- `firewall` default — assumption-challenge / fact-check / general audit

## Source

- Prompt: `config/prompts/dispatcher.txt`
- Wiring: `app.py` event_generator → dispatcher call → mode selection
- Topic-aware CAU attach: `services/rag_retriever.py::_TOPIC_TO_CAU_ID`
- Per-CAU vocab expansion: `services/rag_retriever.py::_CAU_VOCAB_EXPANSIONS`

## Output shape

JSON object surfaced as the `dispatch` SSE event. Always emits — failure
path uses safe `firewall` default.
