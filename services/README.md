# services/

Shared Python service modules used by `app.py`, `trinity_console.py`, self-upgrade, knowledge retrieval, and harness generation.

## Main Groups

| Module | Responsibility |
|---|---|
| `relay_protocol.py` | Canonical parseable protocol for Codex / Claude / Claude Code / ChatGPT / Copilot relay outputs. |
| `runtime_identity.py` | Source of truth for runtime self-identity: URUK protocol carrier; model/provider/app names are backend channels only. |
| `runtime_supervisor.py`, `runtime_dependencies.py` | Production server watchdog plus optional Controller shadow/Ollama lifecycle, sliding-window restart budget, atomic state, dependency health/security probes, logs, and real TCP listener checks. |
| `vessel_scanner.py`, `vessel_context.py` | Runtime hardware identity: scans CPU/RAM/GPU/sensors/buses/ROS, formats VesselProfile for prompts/API, and derives hardware-to-tool gaps for self-upgrade. |
| `vessel_state.py` | Persistent vessel self-state: current location, location history, notes, and calendar commitments injected into vessel context. |
| `knowledge_manifest.py` | Knowledge corpus manifest, ref resolution, duplicate drift checks, health summary. |
| `encoding_audit.py` | Detects content-level mojibake, replacement chars, C1 controls, and private-use characters before RAG/index work. |
| `rag_indexer.py`, `rag_retriever.py` | TF-IDF RAG build and query-time retrieval. |
| `runtime_summary_indexes.py` | Generates RAG-safe summary indexes for experiments, harness episodes, and self-upgrade history. |
| `coordinate_knowledge.py` | Coordinate cards selection and output self-evaluation; request text is routing input, not user judgement. |
| `coordinate_index.py` | Generated deterministic index for Coordinate cards, used by routing, trace, and benchmarks. |
| `context_budget.py`, `cost_aware_router.py`, `inference_governor.py`, `result_cache.py` | Low-cost routing, context budgets, request-level model-call caps, actual inference telemetry, and deterministic result cache. |
| root `failover.py`, `provider_rate_limiter.py` | Cross-node profile isolation plus a process-wide provider queue. Calls to the same free-tier API are spaced across all roles; 429/quota blocks are shared before another profile can repeat them. |
| `controller_policy.py`, `controller_shadow.py`, `controller_learning.py` | Strict controller contract, no-authority local-model shadow comparison, and privacy-gated continuous-learning queue. |
| `harness_episode.py` | Machine-readable replay package for saved sessions. |
| `episode_compare.py` | Deterministic comparison of two harness episodes for regression and report tooling. |
| `prompt_regression.py` | Prompt/protocol fingerprint baseline plus benchmark/quick_eval/episode regression checks. |
| `upgrade_report.py` | Read-only self-upgrade report generator; writes JSON + Markdown summaries from plans, logs, gates, and prompt regression. |
| `upgrade_snapshot.py` | Pre-install checksum manifests and diff reports for self-upgrade rollback auditing. |
| `local_model_router.py`, `small_task_executor.py` | Task-aware bounded local-model workers. Classification, language cleanup, vision, and protocol candidates use separate profiles; local models never hold final authority. |
| `controller_policy.py` | Strict reference teacher for the narrow controller model: route, knowledge layers, task profile, model budget, reviewed tool permission, and escalation decision. |
| `computer_tools.py`, `app_controller.py` | Deterministic computer-use tools and app control surfaces. |
| `task_profiles.py`, `smart_router.py`, `pre_gate.py` | Lightweight routing and model/task selection helpers; cold-start timeouts and task authority boundaries are explicit. |
| `browser_node.py`, `source_registry.py`, `search_engines.py` | External source fetching and source-coordinate checks. |
| `world_simulator.py`, `world_forecast.py`, `world_geotimeline.py`, `world_revision_ledger.py` | Deterministic world graph, filtered history/news scenario weighting, real lat/lon causal timelines, and a persistent correction ledger. Forecast output is a bounded scenario prior, not a prediction oracle. |
| `otel_setup.py` | OpenTelemetry tracing helpers. |
| `civilizational_clock.py`, `physics_compute.py` | Protocol computation helpers. |
| `custom_tools/` | Self-upgrade installed tools. Treat as generated/runtime code. |

## Boundary

Services should be deterministic or bounded helpers. LLM reasoning belongs in:

- `trinity_console.py` for orchestration
- `config/prompts/` for prompt behavior
- `upgrade_engine.py` for self-upgrade execution

Do not hide new prompt formats or model-output contracts inside service docs. The source of truth for relay output remains `relay_protocol.py`.

Windows Copilot is treated as a desktop context backend. It may help with screen, file-search, and Windows-settings tasks, but deterministic install/upgrade authority stays in `upgrade_engine.py` and local validators.

## Provider Rate Limits

`provider_rate_limiter.py` serializes calls by provider, not by Trinity role or
profile name. Default spacing is conservative for the configured free tiers.
An operator can override one provider without editing code, for example:

```powershell
$env:URUK_PROVIDER_MIN_INTERVAL_CEREBRAS="3.0"
$env:URUK_PROVIDER_MIN_INTERVAL_GEMINI="5.0"
```

An active `http_429` or `quota` cooldown cannot be cleared by the normal UI
health reset. `POST /api/nodes/health/reset` requires `{"force": true}` to
override it deliberately. The health endpoint exposes `provider_queue` state.

Coordinate/protocol concept questions selected from `auto` use
`protocol_compact`: Father produces the grounded answer, Spirit audits the
answer framing, and Python performs deterministic Council fusion. This plans
two model calls instead of the full eight-stage path.

## Checks

For service edits, run the relevant targeted test plus the full suite when behavior touches shared contracts:

```powershell
py -m pytest -q tests\test_relay_protocol.py tests\test_knowledge_manifest.py tests\test_rag_retriever.py
py -m pytest -q tests
```

For knowledge-related edits:

```powershell
py tools\encoding_audit.py
py services\runtime_summary_indexes.py --build --quiet
py services\rag_indexer.py --build --quiet
py -m tools.knowledge_audit --summary
```
