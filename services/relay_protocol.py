"""
URUK relay protocol contracts and model-specific adapters.

Core rule: URUK parsers consume one canonical protocol. Individual models may
need different prompt wrappers, but they must all emit the same core blocks.
"""
from __future__ import annotations

from typing import Optional

UPGRADE_ACTIONS = ["validate_code", "install_tools", "hot_reload", "smoke_test", "write_log"]
TOOL_CATEGORIES = "screen|mouse|keyboard|file|state|clipboard|nav|wait|misc"

URUK_CONTEXT = """URUK system context:
- Workspace root: C:\\uruk-trinity-console
- Main app: C:\\uruk-trinity-console\\app.py
- Desktop relay: C:\\uruk-trinity-console\\services\\app_controller.py
- Self-upgrade engine: C:\\uruk-trinity-console\\upgrade_engine.py
- Planner/executor: C:\\uruk-trinity-console\\planner_executor.py
- Tool registry: C:\\uruk-trinity-console\\services\\computer_tools.py
- Custom tools directory: C:\\uruk-trinity-console\\services\\custom_tools
- Runtime config: C:\\uruk-trinity-console\\config\\nodes.yaml
- Upgrade plans: C:\\uruk-trinity-console\\data\\upgrade_plans
- Upgrade audit log: C:\\uruk-trinity-console\\data\\upgrade_log.jsonl
- Runtime identity: user-visible system identity is URUK protocol carrier. Model/app names are backend channels only.

Upgrade method and limits:
- You design upgrade specs only; URUK validates, installs, reloads, tests, and logs.
- Return UPGRADE_EXECUTION_PLAN first when asked for self-upgrade output.
- TOOL_SPEC python_code must define only execute(args: dict) -> dict.
- python_code must not import ToolSpec or ArgSpec.
- Avoid destructive file operations, credential access, shell execution, network downloads, process killing, or modifying core files.
- Return JSON-serializable dicts and catch errors inside execute().
"""

_SKILLS = {
    "general": "uruk-codex-relay",
    "upgrade": "uruk-codex-upgrade",
    "tool_design": "uruk-codex-tool-designer",
    "review": "uruk-codex-review",
}


def infer_relay_mode(message: str, relay_mode: Optional[str] = None) -> str:
    """Infer the canonical URUK relay mode from the message."""
    if relay_mode and relay_mode != "auto":
        return relay_mode if relay_mode in _SKILLS else "general"

    text = (message or "").lower()
    if "[upgrade_plan:" in text or "[upgrade_learn]" in text or "[tool_spec:" in text:
        return "upgrade"
    if "you are a tool designer" in text or '"python_code"' in text or "python_code" in text:
        return "tool_design"
    if "security review" in text or "layer b" in text or ('"concerns"' in text and '"pass"' in text):
        return "review"
    return "general"


def skill_for_mode(mode: str) -> str:
    return _SKILLS.get(mode, _SKILLS["general"])


def upgrade_execution_plan_block(plan_id: str = "<plan_id>") -> str:
    return f"""[UPGRADE_EXECUTION_PLAN:{plan_id}]
{{
  "tool_rules": {{
    "executor_role": "local small model confirms validate/install/reload/test/log; URUK deterministic code executes",
    "global_allowed_actions": ["validate_code", "install_tools", "hot_reload", "smoke_test", "write_log"],
    "safety_rules": ["do not install failed validation tools", "safe specs may auto-install", "high-risk specs are proposal-only and require human confirmation"],
    "stop_conditions": ["all validation failed", "human confirmation required"]
  }},
  "steps": [
    {{"action": "validate_code", "executor_rule": "confirm specs can be statically validated", "allowed_actions": ["validate_code"], "success_criteria": "at least one safe spec passes"}},
    {{"action": "install_tools", "executor_rule": "install only passed specs", "allowed_actions": ["install_tools"], "success_criteria": "custom tool modules are written"}},
    {{"action": "hot_reload", "executor_rule": "reload only custom_tools registry", "allowed_actions": ["hot_reload"], "success_criteria": "new tools appear in registry"}},
    {{"action": "smoke_test", "executor_rule": "smoke-test only newly installed tools", "allowed_actions": ["smoke_test"], "success_criteria": "passed/failed list returned"}},
    {{"action": "write_log", "executor_rule": "write audit log for installed tools only", "allowed_actions": ["write_log"], "success_criteria": "upgrade log records plan id"}}
  ]
}}"""


def tool_spec_block(plan_id: str = "<plan_id>") -> str:
    return f"""[TOOL_SPEC:{plan_id}]
name: <snake_case_name>
description: <clear purpose and return format>
category: <{TOOL_CATEGORIES}>
args:
  - name: <arg>
    type: str|int|float|bool
    required: true|false
    description: <purpose>
python_code: |
  def execute(args: dict) -> dict:
      try:
          return {{"result": "..."}}
      except Exception as e:
          return {{"error": str(e)}}
---"""


def upgrade_output_contract(plan_id: str = "<plan_id>", tool_count: Optional[int] = None) -> str:
    count_line = (
        f"Output exactly {tool_count} [TOOL_SPEC:{plan_id}] block(s), unless a proposed tool is unsafe or duplicated."
        if tool_count is not None
        else f"Output one [TOOL_SPEC:{plan_id}] block per useful safe tool."
    )
    return f"""=== URUK canonical upgrade output protocol ===
All models must emit this same core protocol. Model-specific envelopes are wrappers only.

{upgrade_execution_plan_block(plan_id)}

{tool_spec_block(plan_id)}

Rules:
- Use the exact plan id shown in the request.
- Include exactly one [UPGRADE_EXECUTION_PLAN:{plan_id}] block before TOOL_SPEC blocks.
- {count_line}
- Do not include markdown fences around these blocks.
- Each python_code must define execute(args: dict) -> dict and return JSON-serializable dicts.
- Do not import ToolSpec or ArgSpec in python_code.
- Do not modify URUK core files from python_code.
- Specs with shell, network, credential, destructive file, or core-file behavior are treated as proposal-only until a human confirms them.
"""


def tool_design_json_contract() -> str:
    return f"""{{
  "name": "snake_case_name",
  "description": "clear purpose",
  "category": "{TOOL_CATEGORIES}",
  "needs_visual": false,
  "args": [
    {{"name": "arg", "type": "str|int|float|bool", "required": true, "default": null, "description": "purpose"}}
  ],
  "python_code": "def execute(args: dict) -> dict:\\n    try:\\n        return {{...}}\\n    except Exception as e:\\n        return {{\\\"error\\\": str(e)}}",
  "explanation": "brief summary"
}}"""


def review_json_contract() -> str:
    return '{"pass": true, "concerns": [], "verdict": "safe to promote"}'


def _codex_adapter_prompt(mode: str) -> str:
    skill = skill_for_mode(mode)
    if mode == "upgrade":
        body = (
            "You are a relay backend connected through Codex Desktop. Act for URUK as its upgrade tool designer.\n"
            f"If your Codex environment supports skills, use the `{skill}` skill.\n"
            "Return only the canonical URUK upgrade protocol inside CODEX_RESPONSE:\n"
            "<CODEX_RESPONSE>\n"
            f"{upgrade_output_contract('<plan_id>')}"
            "</CODEX_RESPONSE>\n"
            "<CODEX_STATUS>complete|needs_user|blocked</CODEX_STATUS>\n"
            "<CODEX_FLAGS>code_present</CODEX_FLAGS>"
        )
    elif mode == "tool_design":
        body = (
            "You are a relay backend connected through Codex Desktop. Act for URUK as its tool designer.\n"
            f"If your Codex environment supports skills, use the `{skill}` skill.\n"
            "Return exactly one JSON object inside CODEX_RESPONSE:\n"
            "<CODEX_RESPONSE>\n"
            f"{tool_design_json_contract()}\n"
            "</CODEX_RESPONSE>\n"
            "<CODEX_STATUS>complete|needs_user|blocked</CODEX_STATUS>\n"
            "<CODEX_FLAGS>code_present</CODEX_FLAGS>"
        )
    elif mode == "review":
        body = (
            "You are a relay backend connected through Codex Desktop. Act for URUK as its security/code reviewer.\n"
            f"If your Codex environment supports skills, use the `{skill}` skill.\n"
            "Return strict JSON inside CODEX_RESPONSE:\n"
            "<CODEX_RESPONSE>\n"
            f"{review_json_contract()}\n"
            "</CODEX_RESPONSE>\n"
            "<CODEX_STATUS>complete|needs_user|blocked</CODEX_STATUS>\n"
            "<CODEX_FLAGS>none</CODEX_FLAGS>"
        )
    else:
        body = (
            "You are a relay backend connected through Codex Desktop for URUK Trinity Console.\n"
            f"If your Codex environment supports skills, use the `{skill}` skill.\n"
            "Return the exact answer requested by the original system/user messages, wrapped in this envelope:\n"
            "<CODEX_RESPONSE>\n...your response...\n</CODEX_RESPONSE>\n"
            "<CODEX_STATUS>complete|needs_user|blocked</CODEX_STATUS>\n"
            "<CODEX_FLAGS>code_present,needs_verification</CODEX_FLAGS>"
        )

    return f"""{body}

Envelope rules:
- Put all user-visible content inside CODEX_RESPONSE.
- Do not omit the closing CODEX_RESPONSE tag.
- If the original request requires JSON, put only valid JSON inside CODEX_RESPONSE.
- If the original request requires a special block format, put only that block format inside CODEX_RESPONSE.
- Use needs_user only when you genuinely require more input.
- Use blocked only when the task cannot proceed in this relay context.
"""


def _claude_adapter_prompt(mode: str, app_key: str) -> str:
    if mode == "general":
        return ""

    target = "Claude Code" if app_key == "claude_code" else "Claude Desktop"
    if app_key == "claude_code" and mode == "upgrade":
        # Claude Code already has its own security-sensitive system prompt.
        # The upgrade engine builds a plain review/proposal prompt for it; an
        # extra bracketed adapter can be interpreted as prompt injection.
        return ""

    if mode == "upgrade":
        contract = upgrade_output_contract("<plan_id>")
    elif mode == "tool_design":
        contract = "Return one valid JSON object matching this shape:\n" + tool_design_json_contract()
    elif mode == "review":
        contract = "Return strict JSON matching this shape:\n" + review_json_contract()
    else:
        contract = "Follow the original request exactly."

    return f"""[URUK_MODEL_ADAPTER:{app_key}]
Target model/app: {target}
Runtime identity: URUK protocol carrier. The target model/app is a backend channel only.
Use URUK's canonical core protocol. Do not emit CODEX_RESPONSE tags unless the original request explicitly asks for them.
Model-specific syntax is only a prompt wrapper; the parseable output must remain canonical.

{contract}
[/URUK_MODEL_ADAPTER]"""


def _chatgpt_adapter_prompt(mode: str, plan_id: str = "<plan_id>") -> str:
    if mode == "upgrade":
        contract = upgrade_output_contract(plan_id)
        return (
            "You are acting as a tool designer. "
            "Output exactly the blocks specified below, no extra text before or after.\n\n"
            f"{contract}"
        )
    if mode == "tool_design":
        return (
            "You are acting as a tool designer. "
            "Return exactly one JSON object matching this shape, no extra text:\n"
            f"{tool_design_json_contract()}"
        )
    if mode == "review":
        return (
            "You are acting as a code reviewer. "
            "Return strict JSON matching this shape, no extra text:\n"
            f"{review_json_contract()}"
        )
    return ""


def format_chatgpt_relay_message(
    message: str,
    plan_id: Optional[str] = None,
    relay_mode: Optional[str] = None,
) -> str:
    """Format a relay message for ChatGPT Desktop.

    ChatGPT does not support slash commands or XML skill envelopes, so we use
    a plain structured prompt with an explicit output format contract.

    When the message was pre-formatted by _build_claude_design_prompt (chatgpt
    relay branch), it already contains the identity/self-audit blocks and a
    real plan_id in [TOOL_SPEC:upgrade-...] format. In that case:
      1. Extract the real plan_id so the adapter contract uses it (not literal <plan_id>).
      2. Skip re-adding URUK_CONTEXT + the full body (avoids double-wrapping).
    """
    if "<CHATGPT_RELAY_REQUEST>" in message:
        return message

    import re as _re

    # Detect pre-formatted message from _build_claude_design_prompt (chatgpt branch).
    # Signature: contains a real plan_id in [TOOL_SPEC:upgrade-*] or identity block.
    _preformatted_pid: Optional[str] = None
    _pid_match = _re.search(r"\[TOOL_SPEC:(upgrade-[^\]]+)\]", message)
    if _pid_match:
        _preformatted_pid = _pid_match.group(1)
    elif "════ SYSTEM IDENTITY ════" in message:
        _preformatted_pid = plan_id  # use caller-provided plan_id if any

    if _preformatted_pid:
        # Message already contains the full body with real plan_id — only prepend
        # the adapter with the correct plan_id.  Skip URUK_CONTEXT re-injection.
        mode = infer_relay_mode(message, relay_mode)
        adapter = _chatgpt_adapter_prompt(mode, plan_id=_preformatted_pid)
        return f"{adapter}\n\n{message}" if adapter else message

    # Standard path: raw message, not pre-formatted.
    mode = infer_relay_mode(message, relay_mode)
    adapter = _chatgpt_adapter_prompt(mode, plan_id=plan_id or "<plan_id>")

    if plan_id:
        # Inline the tool spec template so ChatGPT knows exactly what to output.
        spec_template = tool_spec_block(plan_id)
        body = (
            f"{adapter}\n\n"
            f"{URUK_CONTEXT}\n\n"
            f"{message}\n\n"
            f"Output format — use this block template exactly:\n{spec_template}"
        )
    else:
        body = f"{adapter}\n\n{URUK_CONTEXT}\n\n{message}" if adapter else f"{URUK_CONTEXT}\n\n{message}"

    return body


def format_copilot_relay_message(
    message: str,
    relay_mode: Optional[str] = None,
) -> str:
    """Format a relay message for Windows Copilot.

    Copilot's Windows app has no stable local API, so the desktop relay treats it
    like a human-facing chat surface. Keep the output contract explicit because
    URUK still has to parse/audit the result after Copilot responds.
    """
    if "<COPILOT_RELAY_REQUEST>" in message:
        return message
    mode = infer_relay_mode(message, relay_mode)
    adapter = _chatgpt_adapter_prompt(mode)
    context = (
        f"{URUK_CONTEXT}\n\n"
        "Windows Copilot relay role:\n"
        "- Use your Windows context strengths only when the user asks about files, screenshots, UI, or Windows settings.\n"
        "- Do not claim direct access to URUK internals unless the prompt provides that content.\n"
        "- URUK will audit your output before it is shown as final system reasoning.\n"
    )
    body = f"{adapter}\n\n{context}\n\n<COPILOT_RELAY_REQUEST>\n{message}\n</COPILOT_RELAY_REQUEST>"
    return body


def format_codex_relay_message(message: str, relay_mode: Optional[str] = None) -> str:
    if "<CODEX_RELAY_REQUEST>" in message:
        return message
    mode = infer_relay_mode(message, relay_mode)
    skill = skill_for_mode(mode)
    return (
        f"{_codex_adapter_prompt(mode)}\n\n"
        f"{URUK_CONTEXT}\n\n"
        f"<CODEX_SKILL>{skill}</CODEX_SKILL>\n"
        f"If skills are available, invoke/use `{skill}` for this request.\n"
        f"<CODEX_RELAY_MODE>{mode}</CODEX_RELAY_MODE>\n"
        f"<CODEX_RELAY_REQUEST>\n{message}\n</CODEX_RELAY_REQUEST>"
    )


def format_relay_message(app_key: str, message: str, relay_mode: Optional[str] = None) -> str:
    """Apply a model-specific wrapper while preserving URUK's canonical output protocol."""
    target = "claude" if app_key == "cowork" else app_key
    mode = infer_relay_mode(message, relay_mode)

    if target == "codex":
        return format_codex_relay_message(message, relay_mode)

    if target == "claude":
        if message.lstrip().startswith("/uruk-relay"):
            return message
        adapter = _claude_adapter_prompt(mode, target)
        body = f"{adapter}\n\n{message}" if adapter else message
        return f"/uruk-relay {body}"

    if target == "claude_code":
        adapter = _claude_adapter_prompt(mode, target)
        return f"{adapter}\n\n{message}" if adapter else message

    if target == "chatgpt":
        return format_chatgpt_relay_message(message, relay_mode=relay_mode)

    if target == "copilot":
        return format_copilot_relay_message(message, relay_mode=relay_mode)

    return message
