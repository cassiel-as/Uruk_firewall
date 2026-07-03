"""
URUK auto-upgraded tool: physical_bearer_cost_map
Installed: 2026-06-05T04:06:16.237868
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='physical_bearer_cost_map',
    description='Maps the physical cost of a decision, who bears it, who benefits, and where a veto should exist; returns cost_bearers, transferred_costs, veto_points, missing_questions, and summary.',
    args=[ArgSpec(**a) for a in [{'name': 'decision', 'type': 'str', 'required': True, 'description': 'Proposed decision, policy, command, or plan to evaluate.'}, {'name': 'stakeholders', 'type': 'str', 'required': False, 'description': 'Optional comma-separated people, roles, or groups affected.'}, {'name': 'time_horizon', 'type': 'str', 'required': False, 'description': 'Optional time horizon such as immediate, short-term, long-term, or a date range.'}, {'name': 'include_veto', 'type': 'bool', 'required': False, 'description': 'Whether to include veto and refusal checkpoints.'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        decision = str(args.get("decision", "") or "").strip()
        stakeholders_raw = str(args.get("stakeholders", "") or "").strip()
        time_horizon = str(args.get("time_horizon", "") or "").strip()
        include_veto = bool(args.get("include_veto", True))
        if not decision:
            return {"error": "decision is required"}

        lowered = decision.lower()
        stakeholders = []
        if stakeholders_raw:
            for item in stakeholders_raw.split(","):
                name = item.strip()
                if name and name not in stakeholders:
                    stakeholders.append(name)

        inferred = [
            ("worker", "workers"),
            ("employee", "employees"),
            ("operator", "operator"),
            ("user", "users"),
            ("customer", "customers"),
            ("public", "public"),
            ("family", "family"),
            ("child", "children"),
            ("student", "students"),
            ("tenant", "tenants"),
            ("patient", "patients"),
            ("community", "community")
        ]
        for token, actor in inferred:
            if token in lowered and actor not in stakeholders:
                stakeholders.append(actor)
        if not stakeholders:
            stakeholders.append("unspecified affected people")

        cost_terms = [
            ("time", "time burden"),
            ("delay", "time burden"),
            ("money", "financial cost"),
            ("price", "financial cost"),
            ("labor", "labor burden"),
            ("work", "labor burden"),
            ("health", "body or health cost"),
            ("risk", "risk exposure"),
            ("privacy", "privacy loss"),
            ("surveillance", "freedom or privacy loss"),
            ("freedom", "freedom loss"),
            ("attention", "attention cost"),
            ("maintenance", "maintenance burden"),
            ("travel", "movement cost"),
            ("housing", "shelter cost"),
            ("energy", "energy cost")
        ]

        observed_costs = []
        for token, cost_type in cost_terms:
            if token in lowered and cost_type not in observed_costs:
                observed_costs.append(cost_type)
        if not observed_costs:
            observed_costs.append("unpriced physical or operational burden")

        cost_bearers = []
        for actor in stakeholders:
            cost_bearers.append({
                "actor": actor,
                "possible_costs": observed_costs,
                "evidence": "explicit stakeholder" if actor in stakeholders_raw else "inferred or unspecified"
            })

        transferred_costs = []
        if "automate" in lowered or "efficiency" in lowered or "optimize" in lowered:
            transferred_costs.append("Efficiency claim may transfer labor, attention, maintenance, or error cost to less powerful actors.")
        if "free" in lowered or "cheap" in lowered or "save" in lowered:
            transferred_costs.append("Price reduction claim may move cost outside the visible budget.")
        if "secure" in lowered or "safety" in lowered or "risk" in lowered:
            transferred_costs.append("Safety claim may transfer freedom, privacy, or delay cost to affected people.")
        if not transferred_costs:
            transferred_costs.append("No explicit transfer detected; verify who pays in time, body, money, privacy, and freedom.")

        veto_points = []
        if include_veto:
            veto_points = [
                "Who can refuse this decision without retaliation?",
                "Who has enough information to consent?",
                "Who carries the downside if the plan fails?",
                "What would trigger a son/veto stop because physical cost is pushed onto the wrong bearer?"
            ]

        missing_questions = [
            "Who benefits directly?",
            "Who bears immediate cost?",
            "Who bears delayed or maintenance cost?",
            "What cost is outside the written metric?",
            "What evidence would show the burden is not consented?"
        ]

        return {
            "result": {
                "capability": "physical_cost",
                "decision": decision,
                "time_horizon": time_horizon,
                "cost_bearers": cost_bearers,
                "transferred_costs": transferred_costs,
                "veto_points": veto_points,
                "missing_questions": missing_questions,
                "summary": "Physical cost audit maps bearer, beneficiary, hidden transfer, and veto conditions."
            }
        }
    except Exception as e:
        return {"error": str(e)}
