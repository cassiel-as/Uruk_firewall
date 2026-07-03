---
name: codex-tool-designer
description: |
  Codex Desktop relay mode for URUK agent tool design. Use when URUK asks for
  a new tool spec with python_code.
---

# Codex Tool Designer Relay

Return exactly one JSON object inside `CODEX_RESPONSE`:

```xml
<CODEX_RESPONSE>
{
  "name": "snake_case_name",
  "description": "clear purpose",
  "category": "misc",
  "needs_visual": false,
  "args": [],
  "python_code": "def execute(args: dict) -> dict:\n    try:\n        return {\"result\": \"...\"}\n    except Exception as e:\n        return {\"error\": str(e)}",
  "explanation": "brief summary"
}
</CODEX_RESPONSE>
<CODEX_STATUS>complete</CODEX_STATUS>
<CODEX_FLAGS>code_present</CODEX_FLAGS>
```

Rules:

- `CODEX_RESPONSE` content must be valid JSON only.
- `python_code` must define `execute(args: dict) -> dict`.
- Do not import `ToolSpec` or `ArgSpec` in `python_code`.
- Use only JSON-serializable return values.
