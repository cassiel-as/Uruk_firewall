# config/

Runtime configuration and prompt assets for URUK Trinity Console.

## What Lives Here

| Path | Purpose |
|---|---|
| `nodes.yaml` | Local runtime model config. Usually gitignored or treated as operator-specific. |
| `nodes.example.yaml` | Template for node providers, fallback chains, stage overrides, and task profiles. |
| `.env` | Local API keys and secrets. Do not commit real values. |
| `.env.example` | Safe template for required environment variables. |
| `prompts/` | Per-node prompt directives for dispatcher, Stage 1-3, Trinity voices, blackbox, and SCR. |
| `protocol/SKILL.md` | Runtime-loaded sovereign protocol skill bundle. |
| `protocol/references/` | Runtime prompt projections of canonical protocol knowledge. |

## Runtime Flow

`trinity_console.py` loads this folder at startup:

1. `nodes.yaml` defines providers, models, temperatures, fallbacks, and task profiles.
2. `prompts/*.txt` define the behavior of each LLM role.
3. `protocol/SKILL.md` plus selected `protocol/references/*.md` provide the protocol subset injected into node calls.
4. `_canonical_anchor.txt` is prepended to relevant calls to reduce law-name drift.

Local task profiles are selected by `services/local_model_router.py`: `local_classifier`, `local_language`, `vision`, and `local_protocol_candidate`. They are bounded workers, not replacements for Trinity reasoning or final decision authority. Configure both warm `timeout_seconds` and `cold_start_timeout_seconds` for Ollama profiles.

## Editing Rules

- Keep `config/protocol/references/*` aligned with the matching canonical files under `data/` when they are projections of the same concept.
- Do not put API keys in docs or committed config.
- When changing Trinity behavior, update all affected prompt files: `father.txt`, `son.txt`, `spirit.txt`, `council.txt`, and `config/protocol/references/trinity.md`.
- Backup files such as `*.bak` are historical references, not active prompts.

## Checks

```powershell
py -m tools.knowledge_audit --summary
py -m pytest -q tests
```

If frontend labels or prompt expectations changed, also run:

```powershell
node --check static\app.js
```
