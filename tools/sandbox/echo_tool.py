# Echo tool
TOOL_NAME = "echo_tool"
TOOL_METHOD = "tool_run"
TOOL_PARAMS_SCHEMA = {"text": {"type": "str", "required": True}}

def tool_run(params: dict) -> dict:
    """Echo the text param back."""
    return {"status": "ok", "echo": params.get("text", "")}
