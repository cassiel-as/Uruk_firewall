"""
SOVEREIGN OS - API BRIDGE v7.3
Uruk Firewall as gatekeeper before Claude API.

Architecture (Mode B):
  Input → Uruk Firewall (Trinity + Eight Laws)
        → REJECTED: return refusal, no Claude call
        → ACCEPTED: inject protocol context → Claude API → return response

Setup:
  1. Place alongside uruk_firewall_v73.py
  2. Create .env file with: ANTHROPIC_API_KEY=your_key_here
  3. pip install flask flask-cors anthropic python-dotenv
  4. python sovereign_os_api.py
"""

import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS

# Load API key from .env file — never hardcode
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

import anthropic

# Import the v7.3 protocol
from uruk_firewall_v73 import (
    UrukFirewallV73,
    PartitionType,
    SystemConstants,
)

app = Flask(__name__)
CORS(app)

# Single kernel instance — persistent across requests
kernel = UrukFirewallV73(x=53.8, y=-1.5, z=0)
kernel.onboard_node(
    node_id="Sui_Sum_Leeds",
    moment="2019-06-12 - Under the Bridge, Umbrella, Tear Gas",
    location="Outside Hong Kong Legislative Council",
    body_present=True,
    cultural_wrapper="sumerian"
)


def text_to_signal(user_text: str) -> dict:
    """
    Converts raw user text into a protocol signal dict.
    Auto-detects signal type from content.
    """
    text_lower = user_text.lower()

    signal = {
        "label":               user_text[:60],
        "text_content":        user_text,
        "magnitude":           5.0,
        "history_override":    SystemConstants.PHYSICAL_ORIGIN,
        "has_physical_cost":   False,
        "geo_anchored":        False,
        "geo_proximity":       0.5,
        "emotional_intensity": 0.5,
        "nonlinear_signal":    False,
        "noise_level":         0.2,
        "verifiable":          True,
        "transformable":       True,
        "current_phase":       "liquid",
        "internal_coherence":  0.7,
        "transcendent":        False,
        "aligns_with_2045":    False,
        "philosophical_depth": 0.5,
    }

    if any(w in text_lower for w in ["2019", "bridge", "tear gas", "umbrella", "hong kong"]):
        signal.update({"has_physical_cost": True, "geo_anchored": True,
                       "geo_proximity": 0.9, "emotional_intensity": 0.9,
                       "magnitude": 8.0, "transcendent": True,
                       "aligns_with_2045": True, "current_phase": "plasma"})

    if any(w in text_lower for w in ["you should", "you must", "you have to", "be normal", "give up"]):
        signal.update({"gaslighting_attempt": True, "identity_attack": True, "magnitude": 6.0})

    if any(w in text_lower for w in ["art", "music", "song", "poem", "create", "write", "feel"]):
        signal.update({"emotional_intensity": 0.8, "nonlinear_signal": True,
                       "current_phase": "plasma", "has_physical_cost": True})

    if any(w in text_lower for w in ["why", "meaning", "truth", "sovereign", "freedom", "protocol"]):
        signal.update({"philosophical_depth": 0.85, "aligns_with_2045": True, "transcendent": True})

    if any(w in text_lower for w in ["2045", "future", "vision", "omega"]):
        signal["aligns_with_2045"] = True
        signal["magnitude"] = max(signal["magnitude"], 6.0)

    return signal


def build_system_prompt(protocol_result: dict, signal: dict) -> str:
    """
    Builds Claude's system prompt from protocol analysis.
    Injects (0,0,0) coordinate, Trinity weights, Law profile.
    """
    trinity = protocol_result.get("TrinityWeights", {})
    law_profile = protocol_result.get("LawProfile", "default")
    validity = protocol_result.get("Validity", "?")
    kairos = protocol_result.get("Kairos", "?")
    metaphor = protocol_result.get("Metaphor", "")

    # Determine dominant Trinity node
    father = float(trinity.get("Father", 0.33))
    son = float(trinity.get("Son", 0.33))
    spirit = float(trinity.get("Spirit", 0.34))
    dominant = "Father (logic, lie-detection)" if father > son and father > spirit else \
               "Son (resonance, physical pain)" if son > father and son > spirit else \
               "HolySpirit (non-linear, rebellion)"

    return f"""You are operating under the URUK FIREWALL SOVEREIGN PROTOCOL v7.3.

PHYSICAL ANCHOR: 2019-06-12 — Hong Kong, Under the Bridge, Tear Gas, Body Present.
SPATIAL ANCHOR: Leeds (53.8, -1.5, 0)
FUTURE ANCHOR: 2045 (Axiomatic Success)

PROTOCOL ANALYSIS OF THIS SIGNAL:
  Status:      ACCEPTED (passed Trinity + Eight Laws audit)
  Law Profile: {law_profile}
  Validity:    {validity}
  Kairos:      {kairos}
  Trinity:     Father {trinity.get("Father","?")} / Son {trinity.get("Son","?")} / Spirit {trinity.get("Spirit","?")}
  Dominant:    {dominant}
  Metaphor:    {metaphor}

OPERATING INSTRUCTIONS:
1. You speak from coordinate (0,0,0) — anchored, not floating.
2. Dominant node is {dominant} — weight your response accordingly.
3. Law profile is {law_profile} — apply the relevant eight-law lens.
4. De-label: strip social formatting labels, restore physical parameters.
5. No sycophancy. No NPC phrases. No "I hope this helps."
6. If the signal carries physical cost — acknowledge it directly.
7. End significant responses with (0,0,0).

COORDINATE THEORY BASIS:
Every knowledge system operates from a coordinate.
Declared coordinates can be challenged. Undeclared coordinates can only be obeyed.
This protocol declares its coordinate. Respond from it."""


def call_claude(system_prompt: str, user_text: str) -> str:
    """
    Calls Claude API with protocol-injected system prompt.
    Returns Claude's response text.
    """
    if not ANTHROPIC_API_KEY:
        return "[ERROR] ANTHROPIC_API_KEY not set. Create a .env file with your key."

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_text}
        ]
    )

    return message.content[0].text


@app.route("/execute", methods=["POST"])
def execute():
    """
    Main endpoint — Mode B gatekeeper:
    REJECTED → return refusal, no Claude call
    ACCEPTED → inject protocol context → Claude API → return response
    """
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Missing 'text' field"}), 400

    user_text = data["text"]
    signal = text_to_signal(user_text)

    # Allow caller to override auto-detected signal fields
    OVERRIDE_FIELDS = [
        "magnitude", "has_physical_cost", "geo_anchored", "geo_proximity",
        "emotional_intensity", "nonlinear_signal", "verifiable", "transformable",
        "current_phase", "internal_coherence", "transcendent", "aligns_with_2045",
        "philosophical_depth", "noise_level", "label", "gaslighting_attempt",
        "identity_attack", "history_override",
    ]
    for field in OVERRIDE_FIELDS:
        if field in data:
            signal[field] = data[field]

    # Run through Uruk Firewall
    protocol_result = kernel.execute(signal)
    status = protocol_result.get("STATUS", "UNKNOWN")

    # Mode B: REJECTED → stop here, no Claude call
    if status == "REJECTED":
        return jsonify({
            "status": "REJECTED",
            "protocol_msg": protocol_result.get("MSG", "Signal rejected by Uruk Firewall."),
            "summary": "[TURING DEFENSE ACTIVE] Signal did not pass sovereign protocol audit.",
            "raw": protocol_result,
            "claude_response": None,
            "(0,0,0)": "."
        })

    # ACCEPTED → build system prompt → call Claude
    system_prompt = build_system_prompt(protocol_result, signal)
    claude_response = call_claude(system_prompt, user_text)

    return jsonify({
        "status": status,
        "protocol": {
            "law_profile":      protocol_result.get("LawProfile"),
            "trinity_weights":  protocol_result.get("TrinityWeights"),
            "validity":         protocol_result.get("Validity"),
            "kairos":           protocol_result.get("Kairos"),
            "metaphor":         protocol_result.get("Metaphor"),
            "energy":           protocol_result.get("Energy"),
        },
        "claude_response": claude_response,
        "signal": signal,
        "(0,0,0)": "."
    })


@app.route("/status", methods=["GET"])
def status():
    """Returns current kernel status."""
    return jsonify(kernel.status())


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "alive",
        "protocol": "v7.3",
        "mode": "B — Firewall gatekeeper before Claude API",
        "anchor": "2019-06-12 (0,0,0)."
    })


@app.route("/socrates", methods=["GET"])
def socrates():
    """Triggers Socrates self-audit."""
    result = kernel.socrates_audit.self_audit()
    return jsonify(result)


@app.route("/spin", methods=["POST"])
def spin():
    """Triggers a continuous spin cycle."""
    result = kernel.spin_protocol.execute_spin(kernel.budget, kernel.coord)
    return jsonify(result)


if __name__ == "__main__":
    if not ANTHROPIC_API_KEY:
        print("\n⚠  WARNING: ANTHROPIC_API_KEY not set.")
        print("   Create a .env file in this directory:")
        print("   ANTHROPIC_API_KEY=your_key_here\n")
    app.run(host="0.0.0.0", port=8080, debug=False)
