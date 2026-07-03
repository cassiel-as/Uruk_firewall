"""
10-turn conversation stress test for v8.30 fixes.

Topic: AI 對人類自由同社會嘅長遠影響.
Each turn builds on prior turns via in_session_history (the actual schema
the UI uses for client-driven thread state).

Captures per-turn:
  - bytes / event mix
  - 白話版 first sentence (direct-answer test)
  - canonical law name presence (8-law + 4-law)
  - invented law detection (科技律 / 經濟律 / ...)
  - CAU substance citations (CAU-001..012 + key data points)
  - voice metadata (veto / interrupt / rescan)
  - LLM error / fallback flags

Output: /tmp/p10_summary.txt + /tmp/p10_turn_NN.log per turn.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8080"
import tempfile
LOG_DIR = Path(tempfile.gettempdir())   # OS-native tempdir (Windows fix)

QUERIES = [
    "AI 對人類自由同社會嘅長遠影響係咩?",
    "你頭先提到嘅代價轉移,具體邊個社群會承擔得最多?",
    "咁如果我反駁話 AI 其實放大咗個體自由 (例如資訊獲取),你會點答?",
    "用四律分析下你頭先答嘅嗰個自由 vs 代價 trade-off",
    "對照 CAU-011 AI 湧現嘅實質內容,你頭先講嘅有冇 align?",
    "如果逆轉「AI 加速文明」呢個假設,你頭先成個分析會點變?",
    "Module T 方程式二講反格式化窗口 2035 關閉,對你頭先講嘅有咩啟示?",
    "個體應該點對抗 AI 格式化?用具體機制答,唔好淨係講「提升意識」",
    "你頭先成輪論述,自我審計一次:有冇隱藏座標?",
    "最後總結:對於 AI 對人類自由長遠影響,協議嘅 net verdict 係?",
]


def extract_council_text(stream_text: str) -> str:
    for line in stream_text.split("\n"):
        if line.startswith("data: ") and '"role": "council"' in line:
            try:
                d = json.loads(line[6:])
                return (d.get("output") or "")[:3000]
            except Exception:
                pass
    return ""


def extract_event(stream_text: str, event_name: str) -> dict | None:
    pat = re.compile(rf"event: {event_name}\ndata: (\{{.+?\}})\n", re.S)
    m = pat.search(stream_text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def first_sentence(text: str) -> str:
    text = text.strip()
    # Strip leading markdown headers
    text = re.sub(r"^#+\s*[^\n]*\n+", "", text)
    text = re.sub(r"^\(白話版\)?\s*", "", text)
    # First substantive line
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("##") or line.startswith("---"):
            continue
        # Take first sentence (split on 。 ! ? . ）
        m = re.match(r"^(.{20,200}?[。！？.!?])", line)
        if m:
            return m.group(1).strip()
        return line[:200]
    return ""


def run_turn(turn_id: int, query: str, history: list[dict]) -> dict:
    print(f"\n=== Turn {turn_id} ===", flush=True)
    print(f"Q: {query}", flush=True)
    t0 = time.time()
    body = {
        "input": query,
        "pipeline_mode": "firewall",
        "save": False,
        "in_session_history": history,
        "in_session_enabled": True,
    }
    try:
        with httpx.stream(
            "POST", f"{BASE}/api/stream",
            json=body, timeout=600,
        ) as r:
            chunks = []
            for line in r.iter_lines():
                chunks.append(line)
            text = "\n".join(chunks)
    except Exception as e:
        return {"turn_id": turn_id, "query": query, "error": str(e)}

    latency = time.time() - t0
    council = extract_council_text(text)
    stage2 = extract_event(text, "stage2") or {}
    dispatch = extract_event(text, "dispatch") or {}
    cd = extract_event(text, "council_decision") or {}
    rag = extract_event(text, "rag") or {}
    spirit_meta = extract_event(text, "spirit_metadata") or {}
    son_veto = extract_event(text, "son_veto_metadata") or {}

    # Save full stream
    (LOG_DIR / f"p10_turn_{turn_id:02d}.log").write_text(text, encoding="utf-8")

    # Metrics
    invented_pat = re.compile(r"科技律|經濟律|資訊律|社會律|物理律(?!·)|五律")
    metrics = {
        "turn_id": turn_id,
        "query": query,
        "bytes": len(text),
        "latency_s": round(latency, 1),
        "council_first_sentence": first_sentence(council),
        "council_len": len(council),
        "白話版_present": "白話版" in council,
        "invented_laws_count": len(invented_pat.findall(text)),
        "4law_geography": "律一·地理" in council or "地理 (律一" in council,
        "4law_religion": "律二·宗教" in council or "宗教 (律二" in council,
        "4law_psychology": "律三·心理" in council or "心理 (律三" in council,
        "4law_history": "律四·歷史" in council or "歷史 (律四" in council,
        "4law_philosophy": "貫穿律" in council or "philosophy_dispatch" in str(stage2),
        "8law_physics": "律三·物理" in council,
        "8law_geography_filter": "律七·地理" in council or "律七 地理" in council,
        "cau_ids_cited": sorted(set(re.findall(r"CAU-\d{3}", text))),
        "stage2_geo_len": len((stage2.get("geography_analysis") or "").strip()),
        "stage2_rel_len": len((stage2.get("religion_analysis") or "").strip()),
        "stage2_psy_len": len((stage2.get("psychology_analysis") or "").strip()),
        "stage2_his_len": len((stage2.get("history_analysis") or "").strip()),
        "stage2_phi_len": len((stage2.get("philosophy_dispatch") or "").strip()),
        "stage2_llm_ok": not bool(stage2.get("_call_error")),
        "stage2_fallback": stage2.get("_fallback_source", ""),
        "dispatch_mode": dispatch.get("mode", ""),
        "council_verdict": cd.get("verdict", ""),
        "council_weights": cd.get("consensus_weights", {}),
        "rag_block_chars": rag.get("block_chars", 0),
        "spirit_trigger": spirit_meta.get("trigger_mode", ""),
        "spirit_magnitude": spirit_meta.get("magnitude", 0),
        "son_veto_type": son_veto.get("veto_type", ""),
        "son_authentic_suffering": son_veto.get("authentic_suffering_score", 0),
        "rescan_count": cd.get("rescan_count", 0),
    }
    print(f"  bytes={metrics['bytes']} latency={metrics['latency_s']}s")
    print(f"  白話版 first sentence: {metrics['council_first_sentence'][:120]}")
    print(f"  invented={metrics['invented_laws_count']} 4-law(g/r/p/h/phi)={int(metrics['4law_geography'])}/{int(metrics['4law_religion'])}/{int(metrics['4law_psychology'])}/{int(metrics['4law_history'])}/{int(metrics['4law_philosophy'])}")
    print(f"  CAU cited: {metrics['cau_ids_cited']}")
    print(f"  S2 LLM={metrics['stage2_llm_ok']} fallback={metrics['stage2_fallback']!r}")
    return metrics


def main() -> int:
    print(f"=== 10-turn conversation stress test ===")
    print(f"started: {datetime.now().isoformat()}")
    history: list[dict] = []
    all_metrics: list[dict] = []
    for turn_id, query in enumerate(QUERIES, start=1):
        m = run_turn(turn_id, query, history)
        all_metrics.append(m)
        # Build ConvTurn for next turn's history
        council_text = ""
        try:
            stream = (LOG_DIR / f"p10_turn_{turn_id:02d}.log").read_text(encoding="utf-8")
            council_text = extract_council_text(stream)
        except Exception:
            pass
        history.append({
            "turn_id": turn_id,
            "timestamp": datetime.now().isoformat(),
            "input": query,
            "modes": {
                "_default": {
                    "council": council_text[:2500],
                    "verdict": m.get("council_verdict") or "consensus",
                    "veto_type": m.get("son_veto_type") or None,
                }
            },
        })

    # Write summary
    summary_path = LOG_DIR / "p10_summary.json"
    summary_path.write_text(
        json.dumps(all_metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n=== ALL TURNS DONE ===")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
