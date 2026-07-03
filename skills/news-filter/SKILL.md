---
name: news-filter
description: |
  Sovereign news filter — applies the 8-element URUK news audit framework
  to any news article, URL, or news-shaped claim. Detects framing patterns,
  surfaces hidden coordinates, and traces who pays the cost. Mandatory
  whenever a URL is detected in input or `/news` is invoked.

  Triggers: /news / 新聞 / 報導 / 媒體 / URL detected / 港聞 / 國際新聞
---

# News Filter

## 8-element audit

For every news input, surface:

1. **CLAIM** — what the article asserts (literal)
2. **PHYSICAL REALITY** — what physically happened (observable)
3. **HIDDEN COORDINATE** — the unstated framing axis
4. **COST** — who pays, in what currency (energy, attention, freedom, dignity)
5. **CAUSAL NODE** — where this fits in the CAU corpus
6. **FRAMING PATTERN** — which of the 5 v8.1 framing patterns applies (if any)
7. **GAP LEVEL** — Layer 1 / 2 / 3 distance between claim and reality
8. **VERDICT** — surface / weaken / reject

## When it fires

- User invokes `/news`
- BrowserNode detects a URL in input (mandatory: cannot skip news audit on URLs)
- Dispatcher classifies as news / political claim / sourced report

## Source

- Prompt: `config/prompts/filter.txt`
- BrowserNode: `services/browser_node.py`
- Source Registry: `services/source_registry.py` (known-coordinate seed)
- Framing patterns: `external/framing-patterns/` (5 v8.1 patterns)
- Mode wiring: `app.py` event_generator → dispatch → `news` mode

## Output shape

Per-claim block with all 8 elements, plus an aggregate verdict spanning
the whole article. Surface conflicting sources via Source Registry overlay.
