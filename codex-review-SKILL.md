---
name: codex-review
description: |
  Codex Desktop relay mode for URUK security review and code review gates.
---

# Codex Review Relay

Return strict JSON inside `CODEX_RESPONSE`:

```xml
<CODEX_RESPONSE>
{"pass": true, "concerns": [], "verdict": "safe to promote"}
</CODEX_RESPONSE>
<CODEX_STATUS>complete</CODEX_STATUS>
<CODEX_FLAGS>none</CODEX_FLAGS>
```

Rules:

- `CODEX_RESPONSE` content must be valid JSON only.
- `pass` must be a boolean.
- `concerns` must be a list of strings.
- `verdict` must be a short string.
- If rejecting, set `"pass": false` and list concrete concerns.
