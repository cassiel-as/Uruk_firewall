"""
URUK auto-upgraded tool: physical_veto_bearer_map
Installed: 2026-06-05T04:05:54.128183
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='physical_veto_bearer_map',
    description='Maps a proposed decision to physical costs, affected parties, reversibility, and veto checkpoints. Returns JSON with burden rows, risk flags, missing evidence, and questions for the people who bear the cost.',
    args=[ArgSpec(**a) for a in [{'name': 'decision', 'type': 'str', 'required': True, 'description': 'Proposed action, policy, or decision to evaluate.'}, {'name': 'affected_parties', 'type': 'str', 'required': False, 'description': 'Optional comma-separated list of people or groups affected by the decision.'}, {'name': 'timeframe', 'type': 'str', 'required': False, 'description': 'Optional time horizon for cost assessment.'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        decision = str(args.get("decision", "") or "").strip()
        parties_raw = str(args.get("affected_parties", "") or "").strip()
        timeframe = str(args.get("timeframe", "") or "").strip()
        if not decision:
            return {"error": "decision is required"}

        lower = decision.lower()
        parties = []
        if parties_raw:
            for item in parties_raw.replace(";", ",").split(","):
                clean = item.strip()
                if clean:
                    parties.append(clean)
        if not parties:
            parties = ["operator", "direct users", "indirect affected parties"]

        cost_markers = {
            "time_cost": ["time", "delay", "wait", "schedule", "deadline", "overtime"],
            "money_cost": ["money", "fee", "rent", "price", "budget", "salary", "debt", "tax"],
            "labor_cost": ["work", "labor", "manual", "maintain", "care", "admin", "training"],
            "health_safety_cost": ["health", "injury", "safety", "sleep", "stress", "medical", "exposure"],
            "mobility_cost": ["travel", "commute", "move", "transport", "relocate", "access"],
            "attention_cost": ["attention", "monitor", "alert", "interrupt", "notification", "cognitive"],
            "rights_cost": ["consent", "privacy", "surveillance", "restriction", "ban", "permit", "legal"]
        }

        detected_costs = []
        for cost_type, markers in cost_markers.items():
            hits = []
            for marker in markers:
                if marker in lower:
                    hits.append(marker)
            if hits:
                detected_costs.append({"cost_type": cost_type, "markers": hits})

        high_risk_markers = ["irreversible", "forced", "mandatory", "evict", "fire", "ban", "injury", "surveillance", "debt"]
        risk_flags = []
        for marker in high_risk_markers:
            if marker in lower:
                risk_flags.append(marker)

        burden_rows = []
        for party in parties:
            burden_rows.append({
                "party": party,
                "likely_burdens": [item["cost_type"] for item in detected_costs] or ["unknown_cost"],
                "needs_direct_input": True,
                "veto_checkpoint": "required" if risk_flags else "recommended"
            })

        missing_evidence = []
        for item, markers in {
            "measured_cost": ["cost", "estimate", "hours", "amount", "rate"],
            "consent_path": ["consent", "opt in", "opt out", "appeal", "veto"],
            "rollback_plan": ["rollback", "reverse", "undo", "trial", "pilot"],
            "beneficiary": ["benefit", "saves", "gain", "profit", "improve"]
        }.items():
            if not any(marker in lower for marker in markers):
                missing_evidence.append(item)

        return {
            "result": {
                "timeframe": timeframe or None,
                "detected_costs": detected_costs,
                "risk_flags": risk_flags,
                "burden_rows": burden_rows,
                "missing_evidence": missing_evidence,
                "veto_questions": [
                    "Which affected party carries the largest physical or time burden?",
                    "Can that party refuse, appeal, or reverse the decision?",
                    "What measured cost is being transferred away from the decision maker?",
                    "What is the smallest reversible test before full commitment?"
                ],
                "overall_veto_level": "required" if risk_flags else "recommended"
            }
        }
    except Exception as e:
        return {"error": str(e)}
