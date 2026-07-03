"""
URUK auto-upgraded tool: statement_coordinate_locator
Installed: 2026-06-05T11:48:05.651513
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='statement_coordinate_locator',
    description='Analyzes a statement and optional context to identify speaker position, source locus, authority signals, affected groups, missing coordinates, and follow-up questions. Returns a JSON-serializable dict with coordinate_profile and audit_questions.',
    args=[ArgSpec(**a) for a in [{'name': 'statement', 'type': 'str', 'required': True, 'description': 'Statement or claim to analyze for speaker/source coordinates.'}, {'name': 'context', 'type': 'str', 'required': False, 'description': 'Optional surrounding text, source notes, or situational context.'}, {'name': 'claimed_speaker', 'type': 'str', 'required': False, 'description': 'Optional known speaker, author, institution, or channel.'}, {'name': 'include_questions', 'type': 'bool', 'required': False, 'description': 'Whether to include coordinate clarification questions.'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        statement = str(args.get("statement", "")).strip()
        context = str(args.get("context", "")).strip()
        claimed_speaker = str(args.get("claimed_speaker", "")).strip()
        include_questions = bool(args.get("include_questions", True))
        if not statement:
            return {"error": "statement is required"}

        combined = (statement + "\n" + context).lower()

        authority_cues = ["official", "expert", "government", "company", "platform", "research", "policy", "manager", "authority", "committee", "regulator", "source"]
        location_cues = ["local", "regional", "national", "global", "city", "border", "remote", "onsite", "workplace", "school", "hospital", "market"]
        stance_cues = ["we", "they", "our", "their", "must", "should", "cannot", "risk", "benefit", "cost", "harm", "secure", "efficient"]
        affected_cues = ["workers", "users", "patients", "citizens", "families", "tenants", "customers", "students", "operators", "residents", "migrants", "children", "elderly"]

        authority_hits = []
        for cue in authority_cues:
            if cue in combined:
                authority_hits.append(cue)

        location_hits = []
        for cue in location_cues:
            if cue in combined:
                location_hits.append(cue)

        stance_hits = []
        for cue in stance_cues:
            if cue in combined:
                stance_hits.append(cue)

        affected_hits = []
        for cue in affected_cues:
            if cue in combined:
                affected_hits.append(cue)

        missing = []
        if not claimed_speaker:
            missing.append("speaker_or_author")
        if not authority_hits:
            missing.append("institutional_authority")
        if not location_hits:
            missing.append("geographic_or_operational_locus")
        if not affected_hits:
            missing.append("affected_group")
        if "cost" not in combined and "harm" not in combined and "risk" not in combined:
            missing.append("material_stake")

        confidence_points = 0
        if claimed_speaker:
            confidence_points += 2
        confidence_points += min(len(authority_hits), 2)
        confidence_points += min(len(location_hits), 2)
        confidence_points += min(len(affected_hits), 2)
        confidence = "low"
        if confidence_points >= 5:
            confidence = "high"
        elif confidence_points >= 3:
            confidence = "medium"

        questions = []
        if include_questions:
            if "speaker_or_author" in missing:
                questions.append("Who is speaking, and what role or institution do they occupy?")
            if "geographic_or_operational_locus" in missing:
                questions.append("From which place, system position, or operating context is this claim made?")
            if "affected_group" in missing:
                questions.append("Who is directly affected but not currently speaking in the statement?")
            if "material_stake" in missing:
                questions.append("What does the speaker gain or avoid if the statement is accepted?")

        return {
            "result": {
                "coordinate_profile": {
                    "speaker": claimed_speaker if claimed_speaker else "unspecified",
                    "authority_signals": authority_hits,
                    "location_or_locus_signals": location_hits,
                    "stance_signals": stance_hits,
                    "affected_group_signals": affected_hits,
                    "missing_coordinates": missing,
                    "confidence": confidence
                },
                "audit_questions": questions
            }
        }
    except Exception as e:
        return {"error": str(e)}
