---
name: uruk-self-upgrade
description: |
  URUK self-upgrade design skill for Claude Desktop / Cowork.
  Trigger when URUK sends UPGRADE_PLAN, UPGRADE_REQUEST, UPGRADE_LEARN, or asks
  for TOOL_SPEC blocks. The model designs upgrade specs only. URUK validates,
  installs, hot-reloads, smoke-tests, logs, and health-checks.

  Do not directly write files, run shell commands, hot-reload the server, or edit
  URUK core modules from the model side.
---

# URUK Self-Upgrade Skill

## Purpose

This skill makes the model a **tool designer**, not an installer.

URUK Trinity Console sends upgrade requests through the app relay. The model must
return canonical upgrade blocks. URUK then handles all execution through
`upgrade_engine.py`.

Code source of truth:

- Canonical model protocol: `C:\uruk-trinity-console\services\relay_protocol.py`
- Upgrade executor: `C:\uruk-trinity-console\upgrade_engine.py`
- Custom tool output directory: `C:\uruk-trinity-console\services\custom_tools`
- Upgrade plans: `C:\uruk-trinity-console\data\upgrade_plans`
- Upgrade audit log: `C:\uruk-trinity-console\data\upgrade_log.jsonl`

## Trigger Inputs

Use this skill when the request contains any of:

- `[UPGRADE_PLAN:<plan_id>]`
- `[UPGRADE_REQUEST]`
- `[UPGRADE_LEARN]`
- `[TOOL_SPEC:<plan_id>]`
- "design a URUK tool"
- "add a tool to URUK"
- "self-upgrade URUK"

## Required Output

Return one execution plan first, then one or more tool specs:

```text
[UPGRADE_EXECUTION_PLAN:<plan_id>]
{
  "tool_rules": {
    "executor_role": "local small model confirms validate/install/reload/test/log; URUK deterministic code executes",
    "global_allowed_actions": ["validate_code", "install_tools", "hot_reload", "smoke_test", "write_log"],
    "safety_rules": ["do not install failed validation tools", "requires_human=true for dangerous code"],
    "stop_conditions": ["all validation failed", "human confirmation required"]
  },
  "steps": [
    {"action": "validate_code", "executor_rule": "confirm specs can be statically validated", "allowed_actions": ["validate_code"], "success_criteria": "at least one safe spec passes"},
    {"action": "install_tools", "executor_rule": "install only passed specs", "allowed_actions": ["install_tools"], "success_criteria": "custom tool modules are written"},
    {"action": "hot_reload", "executor_rule": "reload only custom_tools registry", "allowed_actions": ["hot_reload"], "success_criteria": "new tools appear in registry"},
    {"action": "smoke_test", "executor_rule": "smoke-test only newly installed tools", "allowed_actions": ["smoke_test"], "success_criteria": "passed/failed list returned"},
    {"action": "write_log", "executor_rule": "write audit log for installed tools only", "allowed_actions": ["write_log"], "success_criteria": "upgrade log records plan id"}
  ]
}

[TOOL_SPEC:<plan_id>]
name: snake_case_name
description: clear purpose and return format
category: screen|mouse|keyboard|file|state|clipboard|nav|wait|misc
args:
  - name: arg
    type: str|int|float|bool
    required: false
    description: purpose
python_code: |
  def execute(args: dict) -> dict:
      try:
          return {"result": "..."}
      except Exception as e:
          return {"error": str(e)}
---
```

Use the exact plan id from the request in every block.

## Hard Limits

- `python_code` must define `execute(args: dict) -> dict`.
- Return only JSON-serializable dictionaries.
- Catch errors inside `execute()`.
- Do not import `ToolSpec` or `ArgSpec` in `python_code`.
- Do not modify `app.py`, `trinity_console.py`, `planner_executor.py`,
  `services/computer_tools.py`, or any other core file.
- Do not run shell commands, kill processes, download code, access credentials,
  write outside `services/custom_tools`, or perform destructive file operations.
- If the request needs a dangerous capability, set `requires_human=true` in the
  execution-plan rationale or return no tool spec.

## Execution Boundary

The model does **not** install anything.

URUK performs:

1. Parse `[UPGRADE_EXECUTION_PLAN:<plan_id>]`.
2. Parse `[TOOL_SPEC:<plan_id>]`.
3. Validate Python syntax and safety.
4. Ask the local small executor model to approve each system action.
5. Write validated tools to `services/custom_tools/`.
6. Hot-reload custom tools.
7. Smoke-test installed tools.
8. Write `data/upgrade_log.jsonl`.
9. Run loop health checks before the next self-upgrade iteration.

## Failure Response

If no safe useful tool can be designed, return:

```text
[UPGRADE_EXECUTION_PLAN:<plan_id>]
{
  "tool_rules": {
    "executor_role": "local small model confirms no safe install should proceed",
    "global_allowed_actions": ["validate_code"],
    "safety_rules": ["no safe tool spec generated"],
    "stop_conditions": ["no safe tool spec generated"]
  },
  "steps": []
}
```

Then explain the reason in plain text only if the relay wrapper permits prose.
