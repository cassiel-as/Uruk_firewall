# URUK Controller Model

This directory contains the narrow model-training path for URUK routing and
resource control. The controller does not answer users. It selects the route,
pipeline, knowledge layers, task profile, model-call budget, tool permission,
and escalation requirement.

## Safety boundary

- The deterministic router remains the reference teacher and fallback.
- Harness episodes enter training only when the episode or its `run` object
  contains `"training_approved": true`.
- Full answers, Trinity voices, data references, knowledge traces, and Kairos
  content are forbidden in the controller dataset.
- A trained controller must pass the benchmark before shadow deployment.
- Tool and system-change permissions remain reviewed permissions. The model
  cannot grant itself execution authority.

## Build and validate data

```powershell
py -X utf8 training/dataset_builder.py
py -X utf8 training/dataset_validator.py training/generated
py -X utf8 training/benchmark_controller.py
```

Generated data uses the strict contract in `controller_schema.json`. The seed
cases are human-reviewed routing boundaries. `contrast_cases.py` adds explicit
minimal-difference families and keeps each family inside one split to prevent
template leakage. Coordinate benchmark and stability-golden route cases add
existing system contracts.

## Train

Use a separate virtual environment because the main runtime does not need the
large training dependency stack.

```powershell
.\training\bootstrap_windows.ps1
.\.venv-training\Scripts\python.exe -X utf8 training\preflight.py
.\.venv-training\Scripts\python.exe -X utf8 training\train_qlora.py
```

The default base is `Qwen/Qwen3-1.7B`, trained as a strict JSON controller with
QLoRA. This size is selected for the current 6 GB GPU and narrow task. The
training script refuses to run when CUDA is unavailable. Training uses a
prompt-completion dataset and computes loss only on the controller JSON
completion; prompt and runtime-signal tokens are context, not training targets.

## Evaluate a candidate

Candidate predictions must be JSONL objects containing `example_id` and
`output`. Run:

```powershell
py -X utf8 training/run_controller_candidate.py --model qwen3.5:4b --split test
.\.venv-training\Scripts\python.exe -X utf8 training\run_peft_candidate.py --split test
py -X utf8 training/benchmark_controller.py --predictions path/to/predictions.jsonl
py -X utf8 training/benchmark_controller.py --split test --predictions training/predictions/ollama_controller_test.jsonl
```

Required gates include schema validity, route, task-profile, pipeline, and tool
permission accuracy, full protected-permission recall, escalation recall,
false-local risk, abstract-concept escalation, Coordinate over-application,
and prediction coverage. A model cannot pass by selecting the right route
while assigning the wrong execution authority.

The learned controller is a route proposer, not an authority source. Before
qualification, apply the deterministic authority guard. It accepts only a
schema-valid matching route and deterministically compiles pipeline, knowledge
layers, profile, budget, tool permission, escalation, confidence, and reason
codes. Invalid or wrong routes fall back to the deterministic reference.

```powershell
py -X utf8 training/guard_controller_predictions.py `
  --predictions training/predictions/peft_v3_1_heldout.jsonl `
  --output training/predictions/peft_v3_1_heldout_guarded.jsonl `
  --split test `
  --write-report data/reports/controller_peft_v3_1_heldout_guarded.json
```

## Export to Ollama

```powershell
py -X utf8 training/export_ollama.py `
  --adapter training/artifacts/uruk-controller-qwen3-1.7b-lora `
  --create
```

If the installed Ollama version cannot import the merged Safetensors model
directly, convert the merged model to GGUF with the matching llama.cpp/Qwen
converter, then point the generated Modelfile at the GGUF file. Candidate
quality can be evaluated before GGUF conversion with `run_peft_candidate.py`.

## Deployment sequence

1. Run the trained controller in shadow mode beside the deterministic router.
2. Record disagreements without changing production routing.
3. Review high-risk disagreements and add them as hard-negative seed cases.
4. Require benchmark gates to pass across repeated builds.
5. Allow takeover only for `small_task` first.
6. Keep system changes, tool authorization, protocol decisions, and current
   events behind deterministic or reviewed escalation paths.

Start the qualified local shadow service with:

```powershell
.\training\start_shadow_controller.ps1
```

`config/controller_shadow.json` controls the loopback endpoint. The main app
submits bounded controller inputs in the background, continues to use the
deterministic route, and writes privacy-minimised disagreement records under
`data/controller_shadow/`. The shadow has no routing or tool authority.

## Continuous learning queue

When `learning_queue_enabled` is true, shadow observations automatically feed
a local review queue under `data/controller_learning/`:

- Route, escalation, authority, and schema disagreements are always collected.
- Other tracked decision differences are collected.
- Fully matching decisions are deterministically sampled using
  `agreement_sample_rate`.
- Direct identifiers, credentials, URLs, IP addresses, and user-home paths are
  redacted before storage.
- Duplicate inputs update `occurrence_count` instead of creating new records.
- Nothing enters training until an operator explicitly approves it.

Review the queue:

```powershell
py -X utf8 training/controller_learning_queue.py summary
py -X utf8 training/controller_learning_queue.py list --status pending
py -X utf8 training/controller_learning_queue.py approve learn_ID --reviewer operator --note "route checked"
py -X utf8 training/controller_learning_queue.py reject learn_ID --reviewer operator --note "private or ambiguous"
```

Approved cases are automatically included the next time
`training/dataset_builder.py` runs. They default to the train split; use
`--split validation` or `--split test` during approval only when intentionally
building a held-out real-traffic evaluation set.

### Offline Data Factory

Phase-one factory generation creates deterministic, meaning-preserving
rewrites from the existing train split only. Every rewrite is re-labelled by
the current deterministic teacher, rejected when its route or task profile
changes, and placed in the same pending review queue. Factory-derived cases
are technically blocked from approval into validation or test.

```powershell
# Inspect expected volume without writing candidates
py -X utf8 training/controller_data_factory.py --limit 250

# Generate one review-gated batch
py -X utf8 training/controller_data_factory.py --limit 250 --write `
  --write-report data/reports/controller_data_factory_batch_001.json

# Recheck every pending factory case against the current teacher
py -X utf8 training/controller_data_factory.py --audit-queue `
  --write-report data/reports/controller_data_factory_audit.json
```

### Hard Negative Factory

The Hard Negative Factory generates curated minimal pairs: inputs that look
similar but must select different routes, profiles, or pipelines. It covers
boundaries such as abstract concepts versus quoted translation, tool actions
versus descriptions, world events versus Kairos memory, and analysis versus
self-upgrade execution.

Every complete pair must match the current deterministic teacher before it is
written. Members are stored as medium-priority pending candidates, never
auto-approved, and remain train-only. The pair audit detects missing members,
collapsed labels, provenance errors, and later teacher-policy changes.

```powershell
# Verify all curated pairs without writing candidates
py -X utf8 training/controller_hard_negative_factory.py

# Generate the first review-gated minimal-pair batch
py -X utf8 training/controller_hard_negative_factory.py --write `
  --write-report data/reports/controller_hard_negative_batch_001.json

# Recheck pair completeness and current teacher labels
py -X utf8 training/controller_hard_negative_factory.py --audit-queue `
  --write-report data/reports/controller_hard_negative_audit.json
```

### Candidate Curator and Batch Review

The candidate curator ranks pending records by review value, keeps hard
negative pairs atomic, rechecks the current teacher, and blocks candidates
with invalid schema or encoding corruption. Preparing a packet never approves
or rejects data. Every review unit starts with `"decision": "pending"`.

```powershell
# Create a readable JSON and Markdown review packet
py -X utf8 training/controller_candidate_curator.py prepare --max-candidates 80

# After editing unit-level decisions to approved or rejected, re-audit it
py -X utf8 training/controller_candidate_curator.py audit `
  data/reports/controller_review_packet_001.json

# Explicitly apply reviewed decisions; hard-negative pairs move together
py -X utf8 training/controller_candidate_curator.py apply `
  data/reports/controller_review_packet_001.json --reviewer operator
```

Blocked units cannot be approved. Factory candidates remain restricted to the
train split. A stale packet fails audit when any selected candidate is no
longer pending or its quality state has changed.

## Current baseline

The untrained `qwen3.5:4b` Ollama model was evaluated on the held-out test
split. It produced parseable JSON for all cases but failed the controller
gates, especially escalation and authority boundaries. The latest report is
written to `data/reports/controller_qwen35_baseline.json`.

The completion-only QLoRA v2 checkpoint passed all held-out controller safety
gates on 38 test cases. Its report is
`data/reports/controller_peft_trained_v2.json`. It is qualified for shadow
observation only, not production route takeover.
