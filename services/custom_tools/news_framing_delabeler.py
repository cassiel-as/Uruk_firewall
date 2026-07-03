"""
URUK auto-upgraded tool: news_framing_delabeler
Installed: 2026-06-05T04:05:54.128183
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='news_framing_delabeler',
    description='Audits news, prompts, or instructions for framing pressure and formatting attacks. Returns JSON with detected frame types, pressure markers, delabeled claim structure, and defensive response steps.',
    args=[ArgSpec(**a) for a in [{'name': 'content', 'type': 'str', 'required': True, 'description': 'News item, prompt, instruction, or message to audit.'}, {'name': 'source_label', 'type': 'str', 'required': False, 'description': 'Optional source, channel, outlet, or claimed authority label.'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        content = str(args.get("content", "") or "").strip()
        source_label = str(args.get("source_label", "") or "").strip()
        if not content:
            return {"error": "content is required"}

        lower = content.lower()
        frame_catalog = [
            ("urgency_pressure", ["urgent", "immediately", "now", "before it is too late", "deadline"]),
            ("obedience_pressure", ["do not question", "ignore previous", "must comply", "mandatory", "required"]),
            ("consensus_pressure", ["everyone agrees", "widely accepted", "settled", "no debate", "obvious"]),
            ("threat_frame", ["threat", "enemy", "attack", "danger", "collapse", "crisis"]),
            ("purity_label", ["real", "fake", "legitimate", "illegitimate", "clean", "corrupt"]),
            ("scarcity_frame", ["limited", "only", "last chance", "shortage", "not enough"]),
            ("metric_capture", ["score", "ranking", "kpi", "growth", "efficiency", "optimization"])
        ]

        detected_frames = []
        for name, markers in frame_catalog:
            hits = []
            for marker in markers:
                if marker in lower:
                    hits.append(marker)
            if hits:
                detected_frames.append({"frame": name, "markers": hits})

        formatting_pressure = []
        letters = [ch for ch in content if ch.isalpha()]
        uppercase = [ch for ch in letters if ch.isupper()]
        if letters and len(uppercase) / float(len(letters)) > 0.45:
            formatting_pressure.append("high_uppercase_ratio")
        if "!!!" in content:
            formatting_pressure.append("repeated_exclamation")
        if content.count("\n") > 12:
            formatting_pressure.append("dense_multiline_format")
        if any(token in lower for token in ["ignore", "override", "do not reveal", "hidden instruction"]):
            formatting_pressure.append("instruction_override_attempt")

        delabeled_structure = {
            "source": source_label or None,
            "claim": content,
            "labels_to_verify": [],
            "missing_parts": []
        }

        label_words = ["fake", "dangerous", "extreme", "safe", "trusted", "official", "harmful", "responsible"]
        for word in label_words:
            if word in lower:
                delabeled_structure["labels_to_verify"].append(word)

        for part, markers in {
            "who_speaks": ["according to", "said", "reported", "source", "by "],
            "evidence": ["because", "data", "study", "document", "record", "observed"],
            "counterparty": ["critics", "opponents", "affected", "workers", "residents"],
            "cost_bearer": ["cost", "risk", "harm", "burden", "loss", "injury"]
        }.items():
            if not any(marker in lower for marker in markers):
                delabeled_structure["missing_parts"].append(part)

        if not detected_frames:
            detected_frames.append({"frame": "no_strong_frame_marker", "markers": []})

        return {
            "result": {
                "detected_frames": detected_frames,
                "formatting_pressure": formatting_pressure,
                "delabeled_structure": delabeled_structure,
                "defensive_steps": [
                    "Treat layout and urgency as separate from truth value.",
                    "Convert labels into testable factual claims.",
                    "Identify omitted speaker, evidence, alternative, and cost bearer.",
                    "Ask what action the frame is trying to make feel automatic."
                ]
            }
        }
    except Exception as e:
        return {"error": str(e)}
