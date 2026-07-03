"""URUK 3D Coordinate Map — visualize Trinity analysis results in coordinate space."""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name="render_coordinate_map",
    description="Generate a 3D coordinate map from Trinity analysis. Plots analysis dimensions (geography/psychology/history) as axes with key coordinate points.",
    category="visualization",
    args=[
        ArgSpec("stage2_output", "str", False, description="JSON string of Stage 2 analysis output"),
        ArgSpec("stage3_output", "str", False, description="JSON string of Stage 3 filter output"),
        ArgSpec("input_text", "str", False, description="Original input text (for labeling)"),
        ArgSpec("output_format", "str", False, description="html or json (default html)"),
    ]
)

def execute(args: dict) -> dict:
    import json
    import math

    try:
        import plotly.graph_objects as go
        import plotly
        HAS_PLOTLY = True
    except ImportError:
        HAS_PLOTLY = False

    if not HAS_PLOTLY:
        return {"ok": False, "error": "plotly_not_installed", "install_hint": "pip install plotly"}

    stage2 = {}
    stage3 = {}
    try:
        if args.get("stage2_output"):
            stage2 = json.loads(args["stage2_output"]) if isinstance(args["stage2_output"], str) else args["stage2_output"]
        if args.get("stage3_output"):
            stage3 = json.loads(args["stage3_output"]) if isinstance(args["stage3_output"], str) else args["stage3_output"]
    except Exception:
        pass

    input_text = str(args.get("input_text", ""))[:60]
    output_fmt = args.get("output_format", "html")

    # Build coordinate points from analysis
    # Each law maps to a dimension
    law_scores = {}
    if stage3:
        for i in range(9):
            for k, v in stage3.items():
                if k.startswith(f"law{i}") and isinstance(v, dict):
                    law_scores[i] = float(v.get("score", 5.0))

    # Default scores if no stage3
    if not law_scores:
        law_scores = {i: 5.0 for i in range(9)}

    # Three primary axes: geography(7), psychology(2), history(4)
    geo   = law_scores.get(7, 5.0)
    psych = law_scores.get(2, 5.0)
    hist  = law_scores.get(4, 5.0)

    # Dominant laws from stage3
    dominant = stage3.get("dominant_laws", [2, 7]) if stage3 else [2, 7]

    # Build visualization points
    points_x, points_y, points_z, labels, sizes, colors = [], [], [], [], [], []

    # Add law coordinate points
    law_names = {0:"愛(0)", 1:"藝術", 2:"心理", 3:"物理", 4:"歷史",
                 5:"科學", 6:"哲學", 7:"地理", 8:"宗教"}
    for i in range(9):
        angle = (i / 9) * 2 * math.pi
        r = law_scores.get(i, 5.0)
        points_x.append(round(r * math.cos(angle), 2))
        points_y.append(round(r * math.sin(angle), 2))
        points_z.append(round(law_scores.get(i, 5.0), 2))
        labels.append(law_names.get(i, f"律{i}"))
        sizes.append(16 if i in dominant else 10)
        colors.append("#7F77DD" if i in dominant else "#B4B2A9")

    # Operator anchor point
    points_x.append(0); points_y.append(0); points_z.append(0)
    labels.append("操作者(0,0,0)")
    sizes.append(20); colors.append("#E24B4A")

    # Input coordinate point
    if geo and psych and hist:
        points_x.append(geo); points_y.append(psych); points_z.append(hist)
        labels.append(f"輸入座標\n{input_text[:30]}")
        sizes.append(18); colors.append("#1D9E75")

    fig = go.Figure(data=[go.Scatter3d(
        x=points_x, y=points_y, z=points_z,
        mode="markers+text",
        text=labels,
        textposition="top center",
        marker=dict(size=sizes, color=colors, opacity=0.85),
    )])

    fig.update_layout(
        title=f"URUK 座標圖: {input_text[:40]}",
        scene=dict(
            xaxis_title="地理律",
            yaxis_title="心理律",
            zaxis_title="歷史律",
            bgcolor="rgba(0,0,0,0)",
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
        margin=dict(l=0, r=0, t=40, b=0),
        height=520,
    )

    if output_fmt == "json":
        return {"ok": True, "format": "json", "figure_json": fig.to_json()}
    else:
        html = plotly.io.to_html(fig, full_html=False, include_plotlyjs="cdn")
        return {"ok": True, "format": "html", "html": html, "point_count": len(points_x)}
