"""Runtime identity contract for URUK model calls.

URUK can route work through Claude Desktop, Codex Desktop, Gemini, Groq,
OpenRouter, Ollama, Copilot, or other backends.  Those are carriers of model
capacity, not the system identity.  This guard keeps every prompt surface from
collapsing backend name into self-identity.
"""

from __future__ import annotations


RUNTIME_IDENTITY_ID = "uruk_protocol_carrier"
RUNTIME_IDENTITY_LABEL = "URUK 協議載體"

RUNTIME_IDENTITY_GUARD = """━━━ RUNTIME IDENTITY / 運行身份 ━━━
你係 URUK 協議載體。
你唔係 Claude Desktop、Claude Code、Codex Desktop、ChatGPT、Gemini、Groq、OpenRouter、Ollama、Windows Copilot 或任何單一模型。
模型、API provider、desktop app、relay target 只係 backend / 工具 / 載體通道。
如果需要提到 provider，只可以講「本次 backend / relay 使用 <provider/model>」；唔好自稱該 provider。
輸出身份保持：URUK 協議載體。
━━━ END RUNTIME IDENTITY ━━━"""


def _vessel_block() -> str:
    try:
        from services.vessel_context import vessel_context_block

        return vessel_context_block()
    except Exception as exc:
        return (
            "━━━ VESSEL PROFILE / Runtime Hardware Identity ━━━\n"
            f"status: unavailable ({type(exc).__name__})\n"
            "━━━ END VESSEL PROFILE ━━━"
        )


def runtime_identity_block() -> str:
    return f"{RUNTIME_IDENTITY_GUARD}\n\n{_vessel_block()}".rstrip()


def with_runtime_identity(system_text: str) -> str:
    text = str(system_text or "")
    if RUNTIME_IDENTITY_GUARD in text:
        if "VESSEL PROFILE / Runtime Hardware Identity" not in text:
            return text.replace(RUNTIME_IDENTITY_GUARD, runtime_identity_block(), 1)
        return text
    return f"{runtime_identity_block()}\n\n{text}".rstrip()
