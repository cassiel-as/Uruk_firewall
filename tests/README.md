# tests/

Regression suite for runtime contracts, knowledge health, Trinity behavior, self-upgrade, and harness packaging.

## Test Map

| Test file | Locks |
|---|---|
| `test_encoding_audit.py` | Content encoding audit for mojibake, C1 controls, replacement chars, and private-use characters. |
| `test_file_service.py` | Sidebar Files tree whitelist, categorized knowledge visibility, and read-only roots. |
| `test_trinity_spirit_modes.py` | Spirit SEMANTIC/STOCHASTIC interrupt behavior and pipeline execution naming. |
| `test_council_summary_extractor.py` | Council summary extraction and user-facing voice dump suppression. |
| `test_knowledge_manifest.py` | Knowledge manifest, duplicate drift, and health summary. |
| `test_rag_retriever.py` | RAG retrieval behavior. |
| `test_runtime_summary_indexes.py` | Generated runtime summary indexes for experiments, harness episodes, and self-upgrade history. |
| `test_vessel_scanner.py` | VesselProfile hardware identity, prompt context block, and hardware-gap derivation. |
| `test_vessel_state.py` | Persistent vessel self-state: location validation, notes, calendar sorting, and prompt context summaries. |
| `test_coordinate_knowledge.py` | Coordinate card selection and output eval. |
| `test_benchmark_runner.py` | Deterministic coordinate foundation benchmark suite. |
| `test_stability_golden.py` | Runtime stability golden cases: routing, Kairos disambiguation, World simulation, and runtime identity. |
| `test_inference_governor.py` | Request-level model-call planning, actual request telemetry, and hard-cap enforcement. |
| `test_failover.py` | Provider error classification, cross-profile failover, cooldown isolation, adaptive failure streaks, budget-health separation, cross-restart persistence, and role-aware fallback ranking. |
| `test_runtime_supervisor.py` | Production launcher command, identity-aware health probe, Controller shadow/Ollama companion commands, local-only listener guard, sliding restart budget, healthy recovery, and atomic watchdog state contract. |
| `test_density_audit.py` | Output density self-audit. |
| `test_harness_episode.py` | Harness episode schema and saved-session companion files. |
| `test_episode_compare.py` | Deterministic harness episode comparison and regression flags. |
| `test_prompt_regression.py` | Prompt/protocol fingerprint baseline and prompt regression checker. |
| `test_small_task_executor.py` | Bounded small-task delegation, deterministic JSON cleanup, fallback behavior, and guardrails. |
| `test_local_model_router.py` | Task-to-local-model assignments, deterministic paths, and large-model escalation boundaries. |
| `test_controller_policy.py`, `test_controller_training.py` | Controller decision contract, privacy-gated dataset build, validation, and benchmark safety gates. |
| `test_controller_candidate.py` | Ollama controller-candidate parsing and held-out split loading. |
| `test_relay_protocol.py` | Codex / Claude relay parseable envelope. |
| `test_smart_router.py` | Smart Auto backend routing, including Copilot for Windows-context tasks. |
| `test_upgrade_engine.py` | Self-upgrade validation/install flow, benchmark gate, and rollback behavior. |
| `test_otel_setup.py` | OpenTelemetry helper behavior. |
| `test_civilizational_clock_canonical.py` | Civilizational clock canonical equations. |
| `test_upgrade_snapshot.py` | Pre-install upgrade snapshot manifest and diff detection for rollback audit. |
| `stress_conversation_10turn.py` | Longer conversational stress utility. |

## Common Commands

```powershell
py -m pytest -q tests
py tools\encoding_audit.py
py tools\benchmark_runner.py
py tools\stability_golden_runner.py
py tools\system_stability_check.py
py tools\episode_compare.py --latest
py tools\prompt_regression_check.py
py -X utf8 training\dataset_builder.py
py -X utf8 training\dataset_validator.py training\generated
py -X utf8 training\benchmark_controller.py
py -m pytest -q tests\test_small_task_executor.py
py -m pytest -q tests\test_trinity_spirit_modes.py
py -m pytest -q tests\test_knowledge_manifest.py tests\test_rag_retriever.py
```

For documentation or knowledge corpus changes, also run:

```powershell
py services\runtime_summary_indexes.py --build --quiet
py services\rag_indexer.py --build --quiet
py -m tools.knowledge_audit --summary
```
