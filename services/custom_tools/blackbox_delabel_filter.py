"""
URUK auto-upgraded tool: blackbox_delabel_filter
Installed: 2026-06-05T04:06:16.237868
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='blackbox_delabel_filter',
    description='Analyzes input language for hidden assumptions, framing defaults, black-boxed terms, and labels that need delabelling; returns result with frames, assumptions, delabelled_terms, and inversion_questions.',
    args=[ArgSpec(**a) for a in [{'name': 'text', 'type': 'str', 'required': True, 'description': 'Statement, claim, instruction, or passage to audit.'}, {'name': 'speaker', 'type': 'str', 'required': False, 'description': 'Optional person, institution, or role speaking the statement.'}, {'name': 'context', 'type': 'str', 'required': False, 'description': 'Optional situation or domain for the statement.'}, {'name': 'include_inversions', 'type': 'bool', 'required': False, 'description': 'Whether to include assumption inversion questions.'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        text = str(args.get("text", "") or "").strip()
        speaker = str(args.get("speaker", "") or "").strip()
        context = str(args.get("context", "") or "").strip()
        include_inversions = bool(args.get("include_inversions", True))
        if not text:
            return {"error": "text is required"}

        lowered = text.lower()
        markers = [
            ("must", "necessity frame", "assumes obligation is already proven"),
            ("obvious", "self-evidence frame", "treats disagreement as irrational"),
            ("just", "minimization frame", "shrinks visible cost or complexity"),
            ("everyone", "consensus frame", "turns claimed majority into evidence"),
            ("security", "security frame", "may trade freedom for risk reduction without accounting"),
            ("efficiency", "efficiency frame", "may hide physical or social cost"),
            ("neutral", "neutrality frame", "may conceal speaker position"),
            ("objective", "objectivity frame", "may conceal metric choice"),
            ("safe", "safety frame", "may suppress who defines safety"),
            ("normal", "normality frame", "uses conformity as proof"),
            ("inevitable", "inevitability frame", "removes agency"),
            ("responsible", "responsibility frame", "may shift burden to another actor")
        ]

        frames = []
        assumptions = []
        for token, frame, assumption in markers:
            if token in lowered:
                frames.append({"trigger": token, "frame": frame})
                assumptions.append(assumption)

        label_map = {
            "terrorist": "person/group accused of political violence; require evidence and source",
            "extremist": "position outside a named norm; identify who defines the norm",
            "illegal": "legal status label; separate person from legal classification",
            "lazy": "moral label; check material constraints and incentives",
            "unskilled": "labor value label; identify skill definition and wage power",
            "consumer": "market role label; recover person, needs, and agency",
            "user": "system role label; recover person, consent, and dependency",
            "enemy": "conflict label; identify threat model and speaker interest",
            "risk": "compressed uncertainty label; ask probability, harm, and bearer",
            "cost": "compressed burden label; ask who pays in money, time, body, or freedom"
        }

        delabelled_terms = []
        for label, replacement in label_map.items():
            if label in lowered:
                delabelled_terms.append({"label": label, "delabel": replacement})

        blackboxed_terms = []
        punctuation = ".,;:!?()[]{}\"'"
        for raw in text.split():
            word = raw.strip(punctuation)
            if len(word) > 3 and (word.isupper() or word.istitle()):
                if word not in blackboxed_terms:
                    blackboxed_terms.append(word)

        if speaker:
            assumptions.append("speaker position may shape what is visible, omitted, or treated as default")
        if context:
            assumptions.append("context may define which metrics are counted and which are excluded")
        if not assumptions:
            assumptions.append("no strong marker found; still check speaker, beneficiary, cost bearer, and excluded alternatives")

        inversion_questions = []
        if include_inversions:
            inversion_questions = [
                "What would change if the claimed necessity were optional?",
                "Who benefits if this frame is accepted without inspection?",
                "Who pays the physical, time, attention, privacy, or freedom cost?",
                "Which alternative becomes invisible under this wording?",
                "What evidence would make the opposite interpretation plausible?"
            ]

        return {
            "result": {
                "capability": "crit_analysis",
                "filter_type": "blackbox_delabel_filter",
                "speaker": speaker,
                "context": context,
                "frames": frames,
                "hidden_assumptions": assumptions,
                "blackboxed_terms": blackboxed_terms,
                "delabelled_terms": delabelled_terms,
                "inversion_questions": inversion_questions
            }
        }
    except Exception as e:
        return {"error": str(e)}
