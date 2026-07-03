"""
URUK auto-upgraded tool: claim_origin_detector
Installed: 2026-06-05T13:00:13.207070
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='claim_origin_detector',
    description='Analyzes a text passage to identify attribution coordinates — who is making each claim and from what institutional or positional context. Returns a list of {speaker|institution, fragment} findings extracted via regex heuristics on attribution verbs and institutional markers.',
    args=[ArgSpec(**a) for a in [{'name': 'text', 'type': 'str', 'required': True, 'description': 'The text passage to scan for speaker attribution and positional markers.'}, {'name': 'max_findings', 'type': 'int', 'required': False, 'description': 'Maximum number of findings to return (default 10).'}]],
    needs_visual=False,
    category='misc',
)

def execute(args: dict) -> dict:
    try:
        import re
        text = args.get("text", "")
        max_findings = int(args.get("max_findings", 10))
        if not text:
            return {"error": "text is required"}
        findings = []
        attr_pats = [
            r'([A-Z][^\.,;\n]{2,60}?)\s+(?:said|says|claimed|claims|argued|argues|noted|notes|warned|states|stated|asserted|declared|told|writes|wrote)\b',
            r'\baccording to\s+([A-Z][^\.,;\n]{2,60})',
        ]
        for pat in attr_pats:
            for m in re.finditer(pat, text):
                speaker = m.group(1).strip()
                s, e = max(0, m.start()-20), min(len(text), m.end()+60)
                findings.append({"speaker": speaker, "fragment": text[s:e].replace("\n"," ").strip()})
                if len(findings) >= max_findings:
                    break
            if len(findings) >= max_findings:
                break
        inst_pat = (r'\b((?:the\s+)?(?:White House|Pentagon|Kremlin|United Nations|European Union|NATO|IMF|WHO|CDC|FBI|CIA|NSA'
                    r'|State Department|Ministry of[^\.,]{2,25}|[A-Z][a-z]+ (?:government|administration|ministry|agency'
                    r'|institute|foundation|committee|council)))\b')
        for m in re.finditer(inst_pat, text):
            inst = m.group(1).strip()
            s, e = max(0, m.start()-10), min(len(text), m.end()+50)
            findings.append({"institution": inst, "fragment": text[s:e].replace("\n"," ").strip()})
            if len(findings) >= max_findings:
                break
        findings = findings[:max_findings]
        return {"result": "ok", "finding_count": len(findings), "findings": findings}
    except Exception as e:
        return {"error": str(e)}
