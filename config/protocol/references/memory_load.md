# Kairos Memory Load Reference

Kairos is not "save everything". Kairos is causality compression: keep the small set of records that changes future system behavior.

## Layers

```
L0  KAIROS_CORE.md              hard physical anchor; always loaded
L1  PHYSICS_CONSTANTS.md        hard physics constants; always loaded
L2  KAIROS_ACTIVE.md            current high-density memory; short and curated
L3  KAIROS_ARCHIVE_INDEX.md     map for long archives; load before archive query
L4  KAIROS_LOG_*.md             long archives; query only, never preload by default
L5  conversation_history/       raw transcripts; replay/debug only, not Kairos memory
```

## Load Rules

### Always

- `data/core/KAIROS_CORE.md`
- `data/core/PHYSICS_CONSTANTS.md`

These files define carrier boundary, physical anchor, and constants. They are not transcript memory.

### Current Kairos State

Load `data/kairos/KAIROS_ACTIVE.md` when the request touches:

- system design or self-upgrade;
- current protocol posture;
- memory rules;
- coordinate cards, benchmark harness, output eval, or prompt regression;
- "上次 / 繼續 / 而家個系統 / 之前改咗咩" style continuity.

### Historical Continuity

Do not load full logs by default.

When older context is needed:

1. load `data/kairos/KAIROS_ARCHIVE_INDEX.md`;
2. select one archive;
3. query that archive narrowly;
4. compress any accepted result back through the Kairos record gate.

### Raw Conversation

`data/conversation_history/` is System 1 transcript history. It can be used for replay, episode compare, or debugging, but it is not canonical Kairos memory.

## Write Rules

Runtime output-density audit may write proposals only:

```
data/kairos/_proposed/KAIROS_PROPOSED_*.md
```

Canonical Kairos memory changes only after operator review.

Accept a record only if it changes one of:

- canonical rule;
- coordinate/worldview structure;
- reusable tool/protocol/evaluator;
- repeated system failure correction;
- future benchmark or upgrade path.

Reject ordinary Q&A, raw tool output, SCR/persona text, session summaries, and unverified LLM phrasing.

## Pseudocode

```python
def memory_load(trigger: str, context: str) -> dict:
    layers = {
        "core": read("data/core/KAIROS_CORE.md"),
        "physics": read("data/core/PHYSICS_CONSTANTS.md"),
    }

    if needs_current_system_state(trigger, context):
        layers["kairos_active"] = read("data/kairos/KAIROS_ACTIVE.md")

    if needs_historical_continuity(context):
        layers["kairos_archive_index"] = read("data/kairos/KAIROS_ARCHIVE_INDEX.md")
        archive = choose_archive(context)
        layers["kairos_archive_excerpt"] = query(archive, context)

    if needs_raw_replay(context):
        layers["conversation_history"] = query("data/conversation_history/", context)

    return layers
```

*(0,0,0).*
