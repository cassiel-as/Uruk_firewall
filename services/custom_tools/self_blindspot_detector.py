"""
URUK auto-upgraded tool: self_blindspot_detector
Installed: 2026-06-04T02:55:53.681696
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='self_blindspot_detector',
    description='偵測系統自身識別到自己嘅盲點或違反',
    args=[ArgSpec(**a) for a in [{'name': 'log_data', 'type': 'str', 'required': True, 'description': '系統日誌數據'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        log_data = args["log_data"]
        blindspots = []
        for entry in log_data:
            if "COUNCIL_REASON" in entry and "載體邊界澄清" in entry["COUNCIL_REASON"]:
                blindspots.append(entry)
        return {"blindspots": blindspots}
    except Exception as e:
        return {"error": str(e)}
