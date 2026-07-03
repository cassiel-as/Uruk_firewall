# skills/

Canonical home for **URUK protocol skill specifications** in the Anthropic
`SKILL.md` convention. Each skill is a self-contained subfolder with at minimum
a `SKILL.md` describing what it does, when to invoke it, and how it works.

## Layout

```
skills/
├── README.md                          (this file)
├── uruk-sovereign-protocol/
│   └── SKILL.md
├── kairos-density-audit/
│   └── SKILL.md
├── blackbox-lab/
│   └── SKILL.md
├── scr-soul-reorg/
│   └── SKILL.md
├── news-filter/
│   └── SKILL.md
├── trinity-audit/
│   └── SKILL.md
├── uruk-audit/
│   └── SKILL.md
├── uruk-learn/
│   └── SKILL.md
├── uruk-self-upgrade/
│   └── SKILL.md
└── master-router/
    └── SKILL.md
```

## Skill file convention

Every `SKILL.md` opens with a YAML frontmatter block:

```yaml
---
name: kebab-case-id          # matches the folder name
description: |
  One-paragraph summary of what the skill does and when it fires.
  Include trigger keywords / phrases the carrier should watch for.
---

# <Display Title>

(body: protocol, parameters, triggers, examples, source-file pointers)
```

## What goes here vs elsewhere

| Location | Purpose | Format | Loaded by |
|---|---|---|---|
| `skills/` | URUK protocol skill **spec docs** | Markdown + YAML frontmatter | (none — doc layer) |
| `data/skills/builtin/` + `data/skills/user/` | **Runtime chat-discoverable** skills | YAML | `skill_registry.py` |
| `config/protocol/SKILL.md` | **Runtime-loaded** sovereign-protocol prompt | Markdown + YAML frontmatter | `trinity_console.py:443` |
| `config/prompts/*.txt` | Per-node LLM **prompt templates** | Plain text | `trinity_console.py` |

The three are distinct concepts — do not collapse them.

- `skills/` is for humans + future tooling to discover the protocol surface.
- `data/skills/` is the live runtime registry for chat-side skills with toggles.
- `config/` holds prompts and protocol text the running pipeline reads.

## Sync notes

- `skills/uruk-sovereign-protocol/SKILL.md` and `config/protocol/SKILL.md`
  must stay in lockstep — the latter is what `trinity_console.py` actually
  loads. When you edit one, update the other (or treat `skills/` as canonical
  and `config/protocol/SKILL.md` as a deploy artifact).
- Self-upgrade skills must follow `services/relay_protocol.py`. They may explain
  the workflow, but must not invent a second parseable output format.
- For Codex Desktop relay skills installed under `%USERPROFILE%\.codex\skills`,
  keep the repo copies (`codex-*-SKILL.md`) semantically aligned with the
  installed copies.

## Adding a new skill

1. `skills/<kebab-case-name>/SKILL.md` with frontmatter (`name`, `description`)
2. Body covers: trigger conditions, inputs, outputs, source-file pointers
3. If the skill has runtime hooks, link to the implementing module/file
4. If the skill is chat-discoverable at runtime, also drop a YAML mirror under
   `data/skills/builtin/` (separate concern — registry-loaded)

## Index of seeded skills

| Name | Implementing source | Runtime entry point |
|---|---|---|
| `uruk-sovereign-protocol` | `config/protocol/SKILL.md` | loaded at startup |
| `kairos-density-audit` | `density_audit.py` | `console.run_density_audit()` |
| `blackbox-lab` | `config/prompts/blackboxlab.txt` | dispatcher mode `blackboxlab` |
| `scr-soul-reorg` | `config/prompts/scr.txt`, `data/protocol/SCR_TEMPLATE.md` | dispatcher mode `scr` |
| `news-filter` | `config/prompts/filter.txt`, `services/source_registry.py` | dispatcher mode `news` |
| `trinity-audit` | `config/prompts/{father,son,spirit,council}.txt` | Stage 4 pipeline |
| `master-router` | `config/prompts/dispatcher.txt` | dispatcher node |
| `uruk-audit` | `app.py` `/api/upgrade/audit`, `upgrade_engine.py` | self-upgrade audit design |
| `uruk-learn` | `app.py` `/api/upgrade/learn`, `upgrade_engine.py` | self-upgrade learn design |
| `uruk-self-upgrade` | `services/relay_protocol.py`, `upgrade_engine.py` | design-only self-upgrade protocol |

## Self-upgrade skill boundary

Current self-upgrade design is **design-only for large models**:

1. Claude/Codex/other model reads the request and outputs canonical blocks.
2. URUK parses `[UPGRADE_EXECUTION_PLAN:<plan_id>]` and `[TOOL_SPEC:<plan_id>]`.
3. URUK validates, installs to `services/custom_tools/`, hot-reloads,
   smoke-tests, logs, and runs loop health checks.

Skill docs should not instruct a model to directly write files, run shell
commands, hot-reload the server, or edit core modules. Those actions belong to
URUK's deterministic execution layer.
