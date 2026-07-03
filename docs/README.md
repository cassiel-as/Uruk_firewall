# URUK Documentation Index

This folder contains operational docs for the running console and its model/tool
integration surfaces.

## Start Here

- [`../README.md`](../README.md) — project overview, runtime modes, self-upgrade
  summary, directory map.
- [`model-onboarding.md`](model-onboarding.md) — required checklist before adding
  a new model, skill, adapter, or self-upgrade failover backend.
- [`SEARCH_API_OPTIONS.md`](SEARCH_API_OPTIONS.md) — search provider options and
  tradeoffs.
- [`../config/README.md`](../config/README.md) — runtime config, prompts, and
  protocol reference editing rules.
- [`../services/README.md`](../services/README.md) — Python service module map.
- [`../data/README.md`](../data/README.md) — knowledge corpus and generated data map.
- [`../static/README.md`](../static/README.md) — frontend UI structure and checks.
- [`../tools/README.md`](../tools/README.md) — CLI and self-upgrade tool areas.
- [`../tests/README.md`](../tests/README.md) — regression suite map.

## Source Of Truth Map

| Area | Code source of truth | Human doc |
|---|---|---|
| Model relay protocol | `services/relay_protocol.py` | `docs/model-onboarding.md` |
| Self-upgrade execution | `upgrade_engine.py` | `README.md` Self-Upgrade section |
| Continuous upgrade loop | `app.py` `/api/upgrade/loop/*` | `README.md` Self-Upgrade section |
| Agent planner/executor | `planner_executor.py` | `README.md` Current System Snapshot |
| Computer-use tools | `services/computer_tools.py` | `skills/uruk-audit/SKILL.md` for audit context |
| Task routing profiles | `services/task_profiles.py`, `config/nodes.yaml` | `README.md` Current System Snapshot |
| Protocol skills | `skills/` and `config/protocol/` | `skills/README.md` |
| Knowledge corpus health | `services/knowledge_manifest.py`, `data/knowledge_manifest.json` | `data/README.md` |
| Trinity runtime behavior | `trinity_console.py`, `config/prompts/*.txt` | `config/README.md`, `data/protocol/TRINITY_AUDIT.md` |
| Frontend control surface | `static/index.html`, `static/app.js` | `static/README.md` |
| Regression coverage | `tests/` | `tests/README.md` |

## Documentation Rules

- Do not redefine parseable model output formats in docs. Link back to
  `services/relay_protocol.py`.
- Do not describe a model skill as the safety boundary. Skills are reinforcement;
  parser validation, deterministic execution, and loop health checks are the
  enforcement layers.
- When adding a new model backend, update `docs/model-onboarding.md` only if the
  onboarding procedure changes. Otherwise update the adapter code and tests.
- When changing self-upgrade behavior, update both `README.md` and any affected
  skill spec under `skills/`.

## Required Checks After Documentation Changes

Run at least:

```powershell
py -m unittest tests.test_relay_protocol
py -m py_compile .\services\relay_protocol.py .\services\app_controller.py .\upgrade_engine.py .\app.py
```

If the change touches frontend self-upgrade controls, also run:

```powershell
node --check .\static\app.js
```
