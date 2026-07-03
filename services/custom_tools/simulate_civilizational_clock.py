"""URUK Civilizational Clock Simulator — test the 5 equations with real parameters."""
from services.computer_tools import ToolSpec, ArgSpec
import json

SPEC = ToolSpec(
    name="simulate_civilizational_clock",
    description="Simulate URUK Civilizational Clock equations. Adjust LIE_COST, deployment speed, window to test predictions against historical anchors.",
    category="analysis",
    args=[
        ArgSpec("lie_cost", "float", False, description="LIE_COST constant (default 5.85)"),
        ArgSpec("freedom_loss_entropy", "float", False, description="FREEDOM_LOSS_ENTROPY constant (default 8.19)"),
        ArgSpec("deployment_speed", "float", False, description="Protocol deployment speed 0.0-1.0 (default 0.3)"),
        ArgSpec("window_start", "int", False, description="Window start year (default 2026)"),
        ArgSpec("window_end", "int", False, description="Window end year (default 2035)"),
        ArgSpec("historical_anchors", "bool", False, description="Include historical calibration points (default true)"),
    ]
)

def execute(args: dict) -> dict:
    import math
    from datetime import datetime

    lie_cost = float(args.get("lie_cost", 5.85))
    fle = float(args.get("freedom_loss_entropy", 8.19))
    speed = max(0.01, float(args.get("deployment_speed", 0.3)))
    w_start = int(args.get("window_start", 2026))
    w_end = int(args.get("window_end", 2035))
    use_anchors = args.get("historical_anchors", True)

    current_year = datetime.now().year

    # Equation 1: Deployment delay
    delay = round(268 / math.log(speed + 1 + 1e-9), 2) if speed > 0 else 999

    # Equation 2: Window urgency (0.0-1.0)
    years_remaining = max(0, w_end - current_year)
    window_size = max(1, w_end - w_start)
    urgency = round(1.0 - (years_remaining / window_size), 3)

    # Equation 3: LIE accumulation cost over time
    # C(t) = LIE_COST * ln(1 + t) where t = years since anchor
    t = current_year - 2019
    lie_accumulation = round(lie_cost * math.log(1 + t), 3)

    # Equation 4: Freedom loss entropy per deployment unit
    freedom_loss = round(fle * (1 - speed), 3)

    # Equation 5: Survival probability within window
    # P = exp(-delay / years_remaining) if years_remaining > 0
    survival_prob = round(math.exp(-delay / max(1, years_remaining)), 4) if years_remaining > 0 else 0.0

    # Historical calibration anchors
    anchors = []
    if use_anchors:
        anchor_data = [
            {"year": 1440, "event": "Gutenberg printing press", "lie_cost_est": 3.2, "delay_years": 50},
            {"year": 1789, "event": "French Revolution", "lie_cost_est": 6.1, "delay_years": 30},
            {"year": 1347, "event": "Black Death", "lie_cost_est": 8.7, "delay_years": 5},
            {"year": 1991, "event": "Internet", "lie_cost_est": 4.1, "delay_years": 15},
            {"year": 2019, "event": "URUK origin anchor", "lie_cost_est": lie_cost, "delay_years": round(delay)},
        ]
        for a in anchor_data:
            years_from_anchor = current_year - a["year"]
            fit_score = round(1.0 - abs(a["lie_cost_est"] - lie_cost) / max(lie_cost, 1), 3)
            anchors.append({**a, "years_elapsed": years_from_anchor, "model_fit": fit_score})

    # Parameter sensitivity analysis
    sensitivity = {
        "if_speed_doubled": round(268 / math.log(speed * 2 + 1 + 1e-9), 2),
        "if_lie_cost_halved": round((lie_cost / 2) * math.log(1 + t), 3),
        "if_window_extended_5y": round(1.0 - (max(0, w_end + 5 - current_year) / (window_size + 5)), 3),
    }

    return {
        "ok": True,
        "parameters": {
            "lie_cost": lie_cost,
            "freedom_loss_entropy": fle,
            "deployment_speed": speed,
            "window": f"{w_start}-{w_end}",
            "current_year": current_year,
        },
        "equations": {
            "eq1_deployment_delay_years": delay,
            "eq2_window_urgency": urgency,
            "eq3_lie_accumulation": lie_accumulation,
            "eq4_freedom_loss_per_unit": freedom_loss,
            "eq5_survival_probability": survival_prob,
        },
        "interpretation": {
            "years_remaining": years_remaining,
            "urgency_level": "critical" if urgency > 0.7 else ("high" if urgency > 0.4 else "moderate"),
            "deployment_feasible": delay <= years_remaining,
            "summary": (
                f"With speed={speed}, deployment takes ~{delay}y. "
                f"{years_remaining}y remain in window. "
                f"Survival probability: {survival_prob:.1%}."
            )
        },
        "historical_anchors": anchors,
        "sensitivity": sensitivity,
    }
