---
name: codex-upgrade
description: |
  Codex Desktop relay mode for URUK self-upgrade plans. Use when the request
  contains UPGRADE_PLAN, UPGRADE_LEARN, or asks for TOOL_SPEC blocks.
---

# Codex Upgrade Relay

URUK uses one canonical core protocol for every model. `CODEX_RESPONSE` is only
the Codex Desktop adapter envelope; the parseable core is the
`UPGRADE_EXECUTION_PLAN` block followed by `TOOL_SPEC` blocks.

Return upgrade output in this exact envelope:

```xml
<CODEX_RESPONSE>
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
</CODEX_RESPONSE>
<CODEX_STATUS>complete</CODEX_STATUS>
<CODEX_FLAGS>code_present</CODEX_FLAGS>
```

Rules:

- Use the exact plan id from the request in every `[TOOL_SPEC:<plan_id>]` header.
- Include one `[UPGRADE_EXECUTION_PLAN:<plan_id>]` block before tool specs.
- Output one block per proposed tool.
- Do not wrap the canonical blocks in markdown fences.
- Each `python_code` must define `execute(args: dict) -> dict`.
- Code must return JSON-serializable dictionaries and handle errors with `try/except`.
- Do not import `ToolSpec` or `ArgSpec`.
- Do not modify URUK core files from generated tools.
