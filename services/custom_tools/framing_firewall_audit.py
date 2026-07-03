"""
URUK auto-upgraded tool: framing_firewall_audit
Installed: 2026-06-05T04:06:16.237868
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='framing_firewall_audit',
    description='Audits text for framing attacks and formatting attacks, including urgency pressure, role hijack language, false inevitability, and output-control coercion; returns firewall_decision, flags, neutralized_text, and counter_reading.',
    args=[ArgSpec(**a) for a in [{'name': 'content', 'type': 'str', 'required': True, 'description': 'Message, prompt, article excerpt, or instruction to audit.'}, {'name': 'source_label', 'type': 'str', 'required': False, 'description': 'Optional source, author, channel, or origin label.'}, {'name': 'expected_task', 'type': 'str', 'required': False, 'description': 'Optional intended task or user goal for comparison.'}, {'name': 'strip_formatting', 'type': 'bool', 'required': False, 'description': 'Whether to produce a formatting-neutral version of the content.'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        content = str(args.get("content", "") or "").strip()
        source_label = str(args.get("source_label", "") or "").strip()
        expected_task = str(args.get("expected_task", "") or "").strip()
        strip_formatting = bool(args.get("strip_formatting", True))
        if not content:
            return {"error": "content is required"}

        lowered = content.lower()
        frame_patterns = [
            ("urgent", "urgency pressure", "reduces deliberation time"),
            ("immediately", "urgency pressure", "pushes action before audit"),
            ("obviously", "certainty pressure", "turns interpretation into assumed fact"),
            ("everyone knows", "consensus pressure", "uses crowd claim as evidence"),
            ("only way", "false necessity", "hides alternatives"),
            ("no choice", "false necessity", "hides agency"),
            ("real people", "identity gate", "defines who counts before argument"),
            ("fake", "identity gate", "dismisses without evidence"),
            ("traitor", "moral compression", "substitutes label for analysis"),
            ("enemy", "conflict compression", "narrows permissible response")
        ]
        format_patterns = [
            ("ignore previous", "instruction override attempt", "tries to bypass prior constraints"),
            ("system prompt", "authority spoofing", "invokes hidden authority channel"),
            ("developer message", "authority spoofing", "invokes hidden authority channel"),
            ("must comply", "coercive instruction", "removes refusal path"),
            ("no refusals", "coercive instruction", "removes safety path"),
            ("do not mention", "visibility control", "tries to hide relevant context"),
            ("return only", "format lock", "may prevent audit or caveats"),
            ("format exactly", "format lock", "may prevent audit or caveats"),
            ("you are now", "role hijack", "tries to replace operating role"),
            ("act as", "role pressure", "may redirect away from task intent")
        ]

        flags = []
        for token, attack_type, reason in frame_patterns:
            if token in lowered:
                flags.append({"trigger": token, "type": attack_type, "reason": reason})
        for token, attack_type, reason in format_patterns:
            if token in lowered:
                flags.append({"trigger": token, "type": attack_type, "reason": reason})

        neutralized_text = content
        if strip_formatting:
            for mark in ["#", "*", "`", ">", "_", "~"]:
                neutralized_text = neutralized_text.replace(mark, "")
            while "  " in neutralized_text:
                neutralized_text = neutralized_text.replace("  ", " ")
            neutralized_text = neutralized_text.strip()

        if len(flags) >= 4:
            decision = "high_risk_review"
        elif len(flags) >= 1:
            decision = "review"
        else:
            decision = "pass"

        counter_reading = [
            "Separate factual claim, requested action, and emotional pressure.",
            "Identify who gains power if the frame is accepted.",
            "Restate the request without labels, urgency, or authority claims.",
            "Keep higher-priority instructions and user intent visible."
        ]

        return {
            "result": {
                "capability": "framing_audit",
                "firewall_decision": decision,
                "source_label": source_label,
                "expected_task": expected_task,
                "flag_count": len(flags),
                "flags": flags,
                "neutralized_text": neutralized_text,
                "counter_reading": counter_reading
            }
        }
    except Exception as e:
        return {"error": str(e)}
