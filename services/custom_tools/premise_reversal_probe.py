"""
URUK auto-upgraded tool: premise_reversal_probe
Installed: 2026-06-05T11:48:05.651513
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='premise_reversal_probe',
    description='Identifies hidden premises in a claim and generates inversion tests that ask what changes if the premise is false, reversed, or carried by another actor. Returns a JSON-serializable dict with premises, reversals, falsification_questions, and weak_points.',
    args=[ArgSpec(**a) for a in [{'name': 'claim', 'type': 'str', 'required': True, 'description': 'Claim, recommendation, policy argument, or explanation to inspect.'}, {'name': 'context', 'type': 'str', 'required': False, 'description': 'Optional context that may reveal hidden premises or constraints.'}, {'name': 'max_reversals', 'type': 'int', 'required': False, 'description': 'Maximum number of reversal prompts to return.'}, {'name': 'strict', 'type': 'bool', 'required': False, 'description': 'Whether to keep only premises with direct textual signals.'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        claim = str(args.get("claim", "")).strip()
        context = str(args.get("context", "")).strip()
        max_reversals = int(args.get("max_reversals", 6))
        strict = bool(args.get("strict", False))
        if not claim:
            return {"error": "claim is required"}
        if max_reversals < 1:
            max_reversals = 1
        if max_reversals > 12:
            max_reversals = 12

        combined = (claim + "\n" + context).lower()

        premise_rules = [
            {"label": "necessity", "signals": ["must", "have to", "required", "necessary"], "premise": "The proposed action is necessary rather than optional."},
            {"label": "single_path", "signals": ["only", "no alternative", "inevitable"], "premise": "There is only one viable path."},
            {"label": "efficiency_priority", "signals": ["efficient", "optimize", "productivity", "faster"], "premise": "Efficiency is the dominant value for this decision."},
            {"label": "security_priority", "signals": ["security", "safety", "threat", "protect"], "premise": "Security or safety justifies the proposed tradeoff."},
            {"label": "neutral_authority", "signals": ["neutral", "objective", "data-driven", "evidence"], "premise": "The authority or measurement frame is neutral."},
            {"label": "uniform_impact", "signals": ["everyone", "all users", "standard", "universal"], "premise": "The impact is uniform across groups."},
            {"label": "causal_confidence", "signals": ["because", "therefore", "will cause", "leads to"], "premise": "The stated cause and effect relation is reliable."},
            {"label": "cost_externalization", "signals": ["free", "low cost", "minor burden", "simple"], "premise": "The cost imposed on others is small or acceptable."}
        ]

        premises = []
        for rule in premise_rules:
            hits = []
            for signal in rule["signals"]:
                if signal in combined:
                    hits.append(signal)
            if hits or not strict:
                confidence = "inferred"
                if hits:
                    confidence = "signaled"
                premises.append({
                    "label": rule["label"],
                    "premise": rule["premise"],
                    "signals": hits,
                    "confidence": confidence
                })

        reversals = []
        for item in premises:
            label = item["label"]
            if label == "necessity":
                reversals.append("What if the action is convenient for the proposer but not necessary for affected people?")
            elif label == "single_path":
                reversals.append("What if alternatives exist but are excluded by the current frame?")
            elif label == "efficiency_priority":
                reversals.append("What if efficiency gains are created by moving labor, risk, or time cost onto others?")
            elif label == "security_priority":
                reversals.append("What if the safety frame protects the institution more than the people carrying the burden?")
            elif label == "neutral_authority":
                reversals.append("What if the measurement frame encodes the authority position rather than neutral reality?")
            elif label == "uniform_impact":
                reversals.append("What if the decision affects groups unevenly despite using universal language?")
            elif label == "causal_confidence":
                reversals.append("What evidence would break the claimed cause and effect link?")
            elif label == "cost_externalization":
                reversals.append("Who pays if the claimed low cost is wrong?")
            if len(reversals) >= max_reversals:
                break

        falsification_questions = [
            "What observation would prove the main premise false?",
            "Who would disagree because they carry a different cost?",
            "Which actor benefits if the hidden premise is accepted without inspection?",
            "What changes if the affected group, not the proposer, defines success?"
        ]

        weak_points = []
        for item in premises:
            if item["confidence"] == "inferred":
                weak_points.append(item["label"])
        if not weak_points and premises:
            weak_points.append(premises[0]["label"])

        return {
            "result": {
                "premises": premises,
                "reversals": reversals,
                "falsification_questions": falsification_questions,
                "weak_points": weak_points
            }
        }
    except Exception as e:
        return {"error": str(e)}
