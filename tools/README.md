# tools/

Command-line tools and self-upgrade tool installation areas.

## Files And Folders

| Path | Purpose |
|---|---|
| `knowledge_audit.py` | CLI wrapper for knowledge manifest and RAG health checks. |
| `encoding_audit.py` | Scan repository text files for mojibake, replacement chars, C1 controls, and private-use characters. |
| `benchmark_runner.py` | Deterministic coordinate foundation benchmark runner; no LLM calls. Also used by self-upgrade post-install gate. |
| `stability_golden_runner.py` | Deterministic runtime contract checks for routing, Kairos, World simulation, and runtime identity. |
| `system_stability_check.py` | One-command stability harness: compile, JS syntax, encoding audit, coordinate benchmark, golden cases, pytest subset, and optional local API smoke. |
| `runtime_watchdog.py` | Supervise the production server, verify URUK runtime identity, use a sliding restart window, restore budget after sustained health, and atomically write machine-readable state. |
| `episode_compare.py` | Compare two harness episode JSON files or the latest pair; no LLM calls. |
| `prompt_regression_check.py` | Check prompt/protocol hash drift against baseline and run deterministic regression gates. |
| `self_upgrade_report.py` | Generate or list self-upgrade JSON + Markdown reports from plans, logs, hard gates, and prompt regression. |
| `small_task_runner.py` | Run bounded low-level tasks through task-aware local workers; model failures fall back or return a full-pipeline handoff signal. |
| `stress_test.py` | Stress/conversation test utility. |
| `active/` | Installed active tools callable by the runtime tool registry. |
| `sandbox/` | Staging area for candidate tools before activation. |

## Tool Lifecycle

Self-upgrade should not directly mutate core behavior from model text. The intended flow is:

1. Model proposes a tool spec through the canonical relay protocol.
2. `upgrade_engine.py` validates the spec.
3. Candidate code is staged and smoke-tested.
4. Validated tools are installed under `services/custom_tools/` or the active tool area, depending on the feature path.
5. Health checks decide whether the loop continues.

## Checks

```powershell
py tools\encoding_audit.py
py -m tools.knowledge_audit --summary
py tools\benchmark_runner.py
py tools\stability_golden_runner.py
py tools\system_stability_check.py
py tools\runtime_watchdog.py --with-shadow --with-ollama
py tools\episode_compare.py --latest
py tools\prompt_regression_check.py
py tools\self_upgrade_report.py
py tools\small_task_runner.py --task classify "latest AI news today"
py -m pytest -q tests\test_upgrade_engine.py tests\test_relay_protocol.py
```

Do not keep secrets or local credentials inside generated tool files.
