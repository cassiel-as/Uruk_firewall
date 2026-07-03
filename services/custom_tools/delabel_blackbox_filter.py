"""
URUK auto-upgraded tool: delabel_blackbox_filter
Installed: 2026-06-05T04:05:54.128183
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='delabel_blackbox_filter',
    description='Deterministically inspects text for hidden assumptions, black-box terms, authority frames, and untested conclusions. Returns JSON with findings, missing coordinates, neutral rewrite hints, and verification questions.',
    args=[ArgSpec(**a) for a in [{'name': 'text', 'type': 'str', 'required': True, 'description': 'Text or claim to inspect.'}, {'name': 'speaker', 'type': 'str', 'required': False, 'description': 'Optional stated speaker or institution behind the claim.'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        text = str(args.get("text", "") or "").strip()
        speaker = str(args.get("speaker", "") or "").strip()
        if not text:
            return {"error": "text is required"}

        lower = text.lower()
        checks = [
            {
                "type": "authority_frame",
                "markers": ["experts say", "science says", "everyone knows", "official", "approved", "trusted source"],
                "assumption": "Authority is being used as a substitute for evidence or mechanism."
            },
            {
                "type": "inevitability_frame",
                "markers": ["must", "cannot avoid", "inevitable", "no alternative", "only option", "have to"],
                "assumption": "A policy or choice is framed as unavoidable before alternatives are compared."
            },
            {
                "type": "label_substitution",
                "markers": ["dangerous", "extreme", "safe", "normal", "responsible", "misinformation", "harmful"],
                "assumption": "A label may be replacing the underlying claim, evidence, or cost bearer."
            },
            {
                "type": "blackbox_term",
                "markers": ["system", "algorithm", "market", "security", "efficiency", "community standards", "best practice"],
                "assumption": "A broad term may hide who decided, by what rule, and who benefits."
            },
            {
                "type": "false_binary",
                "markers": ["either", "or else", "with us", "against us", "choice is simple"],
                "assumption": "The text may erase middle options, staged options, or local veto rights."
            }
        ]

        findings = []
        for check in checks:
            hits = []
            for marker in check["markers"]:
                if marker in lower:
                    hits.append(marker)
            if hits:
                findings.append({
                    "type": check["type"],
                    "severity": "medium",
                    "evidence": hits,
                    "hidden_assumption": check["assumption"]
                })

        missing_coordinates = []
        if not speaker:
            missing_coordinates.append("speaker")
        for key, markers in {
            "beneficiary": ["benefit", "profit", "gain", "advantage"],
            "cost_bearer": ["cost", "risk", "burden", "harm", "loss"],
            "decision_rule": ["because", "therefore", "based on", "rule", "criteria"],
            "alternative_options": ["alternative", "option", "instead", "tradeoff"]
        }.items():
            if not any(marker in lower for marker in markers):
                missing_coordinates.append(key)

        rewrite_hints = [
            "Replace labels with the concrete behavior or claim being judged.",
            "Name the speaker, beneficiary, cost bearer, and decision rule.",
            "Separate observation, inference, value judgment, and requested action.",
            "Ask what evidence would change the conclusion."
        ]

        if not findings:
            findings.append({
                "type": "low_signal",
                "severity": "low",
                "evidence": [],
                "hidden_assumption": "No strong marker was detected; still verify coordinates before accepting the frame."
            })

        return {
            "result": {
                "speaker": speaker or None,
                "findings": findings,
                "missing_coordinates": missing_coordinates,
                "rewrite_hints": rewrite_hints,
                "verification_questions": [
                    "Who is speaking, and from which institutional or material position?",
                    "What is being assumed before evidence is shown?",
                    "Who benefits if this frame is accepted?",
                    "Who pays the cost if this recommendation is wrong?"
                ]
            }
        }
    except Exception as e:
        return {"error": str(e)}
