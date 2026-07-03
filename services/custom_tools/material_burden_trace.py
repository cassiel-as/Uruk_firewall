"""
URUK auto-upgraded tool: material_burden_trace
Installed: 2026-06-05T11:48:05.651513
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='material_burden_trace',
    description='Maps a decision or proposal into likely material burdens across time, money, risk, labor, access, maintenance, and autonomy. Returns a JSON-serializable dict with burden_dimensions, likely_carriers, missing_inputs, and fairness_checks.',
    args=[ArgSpec(**a) for a in [{'name': 'decision', 'type': 'str', 'required': True, 'description': 'Decision, proposal, policy, or action to analyze for material burden.'}, {'name': 'context', 'type': 'str', 'required': False, 'description': 'Optional context about implementation, stakeholders, or constraints.'}, {'name': 'proposer', 'type': 'str', 'required': False, 'description': 'Optional person, group, or institution proposing the decision.'}, {'name': 'horizon', 'type': 'str', 'required': False, 'description': 'Optional time horizon such as immediate, short_term, long_term, or lifecycle.'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        decision = str(args.get("decision", "")).strip()
        context = str(args.get("context", "")).strip()
        proposer = str(args.get("proposer", "")).strip()
        horizon = str(args.get("horizon", "")).strip()
        if not decision:
            return {"error": "decision is required"}

        combined = (decision + "\n" + context).lower()

        carrier_cues = ["workers", "users", "patients", "citizens", "families", "tenants", "customers", "students", "operators", "residents", "migrants", "contractors", "public", "staff"]
        carriers = []
        for cue in carrier_cues:
            if cue in combined:
                carriers.append(cue)
        if not carriers:
            carriers.append("unspecified affected people")

        dimensions = {
            "time": ["delay", "waiting", "time", "queue", "schedule", "deadline"],
            "money": ["price", "fee", "cost", "budget", "rent", "wage", "funding", "payment"],
            "risk": ["risk", "harm", "injury", "failure", "exposure", "liability", "unsafe"],
            "labor": ["work", "manual", "staff", "operator", "maintenance", "training", "support"],
            "access": ["access", "disabled", "eligibility", "distance", "transport", "language", "login"],
            "attention": ["monitor", "attention", "review", "notice", "alert", "paperwork"],
            "autonomy": ["consent", "choice", "mandatory", "must", "forced", "surveillance", "control"]
        }

        burden_dimensions = {}
        for dimension in dimensions:
            hits = []
            for cue in dimensions[dimension]:
                if cue in combined:
                    hits.append(cue)
            burden_dimensions[dimension] = {
                "signals": hits,
                "detected": len(hits) > 0
            }

        missing_inputs = []
        if not proposer:
            missing_inputs.append("proposer_or_decision_owner")
        if not horizon:
            missing_inputs.append("time_horizon")
        if carriers == ["unspecified affected people"]:
            missing_inputs.append("named_affected_groups")
        if "fallback" not in combined and "appeal" not in combined and "opt out" not in combined:
            missing_inputs.append("escape_or_appeal_path")
        if "measure" not in combined and "metric" not in combined and "audit" not in combined:
            missing_inputs.append("measurement_method")

        fairness_checks = [
            "Identify who receives benefit, who absorbs downside, and whether these are the same people.",
            "Check whether the proposer can avoid costs that affected groups cannot avoid.",
            "Check whether the burden grows over time after initial deployment.",
            "Check whether an appeal, refusal, or fallback path exists for high-burden groups."
        ]

        asymmetry_notes = []
        if proposer:
            asymmetry_notes.append("Compare proposer exposure against carrier exposure for each detected burden dimension.")
        if burden_dimensions["autonomy"]["detected"]:
            asymmetry_notes.append("Autonomy burden detected; verify consent and refusal paths.")
        if burden_dimensions["access"]["detected"]:
            asymmetry_notes.append("Access burden detected; verify who is excluded by distance, language, eligibility, or interface requirements.")

        return {
            "result": {
                "decision": decision,
                "proposer": proposer if proposer else "unspecified",
                "horizon": horizon if horizon else "unspecified",
                "likely_carriers": carriers,
                "burden_dimensions": burden_dimensions,
                "missing_inputs": missing_inputs,
                "asymmetry_notes": asymmetry_notes,
                "fairness_checks": fairness_checks
            }
        }
    except Exception as e:
        return {"error": str(e)}
