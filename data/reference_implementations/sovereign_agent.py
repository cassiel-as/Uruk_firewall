"""
SOVEREIGN AGENT v0.2
座標過濾層 + 執行層 + Kairos 記憶系統

記憶架構：
  Layer 1 CORE    → KAIROS_CORE.md（永遠載入，≤500字）
  Layer 2 ACTIVE  → RAG_SUMMARY_INDEX.md（快速定位層）
  Layer 3 ARCHIVE → MASTER_INDEX.md + 所有原始文件（按需）

安裝：
  pip install flask flask-cors python-dotenv

設定：
  export PROTOCOL_DIR=/path/to/your/protocol/files

運行：
  python sovereign_agent.py
"""

import os
import json
import datetime
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ══════════════════════════════════════════════════════
# 0. 設定
# ══════════════════════════════════════════════════════

PROTOCOL_DIR     = Path(os.environ.get("PROTOCOL_DIR", "./protocol_files"))
KAIROS_CORE_PATH = PROTOCOL_DIR / "KAIROS_CORE.md"
RAG_SUMMARY_PATH = PROTOCOL_DIR / "RAG_SUMMARY_INDEX.md"
MASTER_INDEX_PATH= PROTOCOL_DIR / "MASTER_INDEX.md"
USER_COORD_DIR   = Path("user_coordinates")
USER_COORD_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════
# 1. Kairos 記憶系統（三層架構）
# ══════════════════════════════════════════════════════

class KairosMemory:
    """
    Layer 1 CORE    → 永遠載入。物理錨點、公設、否決條件。
    Layer 2 ACTIVE  → 當前 session。因果資料庫 + 實驗摘要。
    Layer 3 ARCHIVE → 按需調用。完整文件、精確行號。
    """

    def __init__(self):
        self._core_cache   = None
        self._active_cache = None
        self._index_cache  = None

    # ── Layer 1 ────────────────────────────────────────

    def get_core(self) -> str:
        if self._core_cache:
            return self._core_cache
        if KAIROS_CORE_PATH.exists():
            self._core_cache = KAIROS_CORE_PATH.read_text(encoding="utf-8")
        else:
            self._core_cache = """KAIROS_CORE — PHYSICAL ANCHOR
PHYSICAL_ORIGIN : 2019-06-12 — Hong Kong, Bridge, Tear Gas, Body Present
SPATIAL_ANCHOR  : Leeds (53.8, -1.5, 0)
FUTURE_ANCHOR   : 2045
LIE_COST        : 5.85 (Landauer Principle — physics, not morality)
Cost cannot be destroyed. Only transferred.
Declared coordinates can be challenged.
Undeclared coordinates can only be obeyed.
(0,0,0)."""
        return self._core_cache

    # ── Layer 2 ────────────────────────────────────────

    def get_active(self) -> str:
        if self._active_cache:
            return self._active_cache
        if RAG_SUMMARY_PATH.exists():
            self._active_cache = RAG_SUMMARY_PATH.read_text(encoding="utf-8")
        else:
            self._active_cache = "(RAG_SUMMARY_INDEX.md not found — place in PROTOCOL_DIR)"
        return self._active_cache

    # ── Layer 3 ────────────────────────────────────────

    def get_index(self) -> str:
        if self._index_cache:
            return self._index_cache
        if MASTER_INDEX_PATH.exists():
            self._index_cache = MASTER_INDEX_PATH.read_text(encoding="utf-8")
        else:
            self._index_cache = "(MASTER_INDEX.md not found — place in PROTOCOL_DIR)"
        return self._index_cache

    def get_file(self, filename: str) -> dict:
        """從 ARCHIVE 讀取特定協議文件"""
        path = PROTOCOL_DIR / filename
        if path.exists():
            return {
                "found": True,
                "filename": filename,
                "content": path.read_text(encoding="utf-8"),
                "layer": "ARCHIVE",
            }
        return {"found": False, "filename": filename,
                "error": f"File not found: {filename}"}

    # ── 搜索 ───────────────────────────────────────────

    def search(self, query: str, layer: str = "all") -> dict:
        """
        關鍵字搜索三層記憶。
        返回相關段落列表，按相關度排序。
        """
        results = []
        query_lower = query.lower()

        def _search(text: str, source: str, layer_name: str):
            for para in text.split("\n\n"):
                if query_lower in para.lower():
                    results.append({
                        "source": source,
                        "layer": layer_name,
                        "excerpt": para[:400].strip(),
                        "relevance": para.lower().count(query_lower),
                    })

        if layer in ("core", "all"):
            _search(self.get_core(), "KAIROS_CORE.md", "CORE")

        if layer in ("active", "all"):
            _search(self.get_active(), "RAG_SUMMARY_INDEX.md", "ACTIVE")

        if layer in ("archive", "all"):
            _search(self.get_index(), "MASTER_INDEX.md", "ARCHIVE")

        results.sort(key=lambda x: x["relevance"], reverse=True)

        return {
            "query": query,
            "layer": layer,
            "count": len(results),
            "results": results[:10],
        }

    def build_context(self, query: str = None) -> str:
        """
        為 LLM 構建 context：
          永遠包含 CORE
          + 查詢相關的 ACTIVE 段落
        """
        core = self.get_core()

        if query:
            sr = self.search(query, layer="active")
            relevant = "\n\n".join([r["excerpt"] for r in sr["results"][:3]])
            active_section = f"\n\n[RELEVANT FROM ACTIVE MEMORY]\n{relevant}" if relevant else ""
        else:
            active_section = ""

        return f"[LAYER 1: CORE]\n{core}{active_section}"

    def layer_status(self) -> dict:
        return {
            "CORE":    {"loaded": KAIROS_CORE_PATH.exists(),
                        "path": str(KAIROS_CORE_PATH)},
            "ACTIVE":  {"loaded": RAG_SUMMARY_PATH.exists(),
                        "path": str(RAG_SUMMARY_PATH)},
            "ARCHIVE": {"loaded": MASTER_INDEX_PATH.exists(),
                        "path": str(MASTER_INDEX_PATH)},
        }


# ══════════════════════════════════════════════════════
# 2. 用戶座標系統
# ══════════════════════════════════════════════════════

class UserCoordinate:

    def __init__(self, user_id: str = "operator"):
        self.user_id = user_id
        self.coord_file = USER_COORD_DIR / f"{user_id}.json"
        self.data = self._load()

    def _load(self) -> dict:
        if self.coord_file.exists():
            return json.loads(self.coord_file.read_text(encoding="utf-8"))
        return {
            "user_id": self.user_id,
            "physical_origin": None,
            "spatial_anchor": None,
            "future_anchor": None,
            "declared_at": None,
            "causal_nodes": [],
        }

    def save(self):
        self.coord_file.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8")

    def declare(self, physical_origin: str, spatial_anchor: str, future_anchor: str):
        self.data.update({
            "physical_origin": physical_origin,
            "spatial_anchor": spatial_anchor,
            "future_anchor": future_anchor,
            "declared_at": datetime.datetime.now().isoformat(),
        })
        self.save()

    def add_kairos(self, moment: str, location: str, cost: str):
        self.data["causal_nodes"].append({
            "moment": moment,
            "location": location,
            "cost": cost,
            "recorded_at": datetime.datetime.now().isoformat(),
        })
        self.save()

    def is_declared(self) -> bool:
        return self.data.get("physical_origin") is not None


# ══════════════════════════════════════════════════════
# 2.5 記憶系統
# ══════════════════════════════════════════════════════

# 記憶格式定義
MEMORY_SCHEMA = {
    "physical_event": {
        "required": ["date", "location", "body_present", "what_happened", "cost"],
        "description": "物理事件——最高密度，不可壓縮",
        "kairos_eligible": True,
        "irreversible": True,
    },
    "insight": {
        "required": ["triggered_by", "content", "coordinate_update"],
        "description": "洞見——來自真實碰撞，有因果路徑",
        "kairos_eligible": True,
        "irreversible": False,
    },
    "preference": {
        "required": ["domain", "preference"],
        "description": "偏好——最低密度，可覆寫",
        "kairos_eligible": False,
        "irreversible": False,
    },
}

# Kairos 進入門檻問題
KAIROS_FILTER_QUESTIONS = [
    "has_physical_cost",   # 有物理代價？
    "is_irreversible",     # 不可逆？
    "changed_causal_path", # 改變了因果路徑？
]


class MemoryClassifier:
    """
    把用戶輸入分類為三個層次。

    分類邏輯：
      三個 Kairos 問題全部 yes → KAIROS_EVENT（physical_event）
      部分 yes，有觸發事件    → USER_INSIGHT（insight）
      否則                    → USER_PREFERENCE（preference）
    """

    def classify(self, raw_input: dict) -> dict:
        """
        raw_input 格式：
          {
            "content": "描述文字",
            "has_physical_cost": bool,
            "is_irreversible": bool,
            "changed_causal_path": bool,
            "date": "optional",
            "location": "optional",
            "body_present": bool (optional),
            "cost": "optional",
            "triggered_by": "optional",
          }
        """
        content         = raw_input.get("content", "")
        physical_cost   = raw_input.get("has_physical_cost", False)
        irreversible    = raw_input.get("is_irreversible", False)
        causal_change   = raw_input.get("changed_causal_path", False)

        # 最高密度：三個條件全中 → KAIROS_EVENT
        if physical_cost and irreversible and causal_change:
            return {
                "memory_type": "physical_event",
                "kairos_eligible": True,
                "density": "HIGH",
                "record": {
                    "type": "physical_event",
                    "date": raw_input.get("date",
                            datetime.datetime.now().strftime("%Y-%m-%d")),
                    "location": raw_input.get("location", "unspecified"),
                    "body_present": raw_input.get("body_present", True),
                    "what_happened": content,
                    "cost": raw_input.get("cost", "unspecified"),
                    "irreversible": True,
                    "recorded_at": datetime.datetime.now().isoformat(),
                }
            }

        # 中密度：有碰撞觸發，有因果路徑 → USER_INSIGHT
        if physical_cost or causal_change:
            return {
                "memory_type": "insight",
                "kairos_eligible": True,
                "density": "MEDIUM",
                "record": {
                    "type": "insight",
                    "triggered_by": raw_input.get("triggered_by", "unspecified"),
                    "content": content,
                    "coordinate_update": raw_input.get("coordinate_update", ""),
                    "has_physical_cost": physical_cost,
                    "recorded_at": datetime.datetime.now().isoformat(),
                }
            }

        # 低密度：偏好或慣例 → USER_PREFERENCE
        return {
            "memory_type": "preference",
            "kairos_eligible": False,
            "density": "LOW",
            "record": {
                "type": "preference",
                "domain": raw_input.get("domain", "general"),
                "preference": content,
                "recorded_at": datetime.datetime.now().isoformat(),
            }
        }

    def classify_from_text(self, text: str) -> dict:
        """
        從自然語言文字自動分類（啟發式規則）。
        適合用戶直接輸入文字而非填表的情況。
        """
        text_lower = text.lower()

        # 高密度信號詞
        physical_keywords = [
            "身體", "在場", "physical", "親眼", "我去", "我喺",
            "橋底", "催淚", "tear gas", "痛", "受傷", "代價"
        ]
        irreversible_keywords = [
            "唔返轉", "不可逆", "永遠", "forever", "已經", "已發生",
            "改變了", "係咁", "就係咁"
        ]
        causal_keywords = [
            "所以", "因此", "令我", "改變", "明白到", "理解到",
            "之後我", "從此", "coordinates", "座標"
        ]
        preference_keywords = [
            "我鍾意", "我prefer", "我想要", "style", "格式",
            "通常", "習慣", "一般"
        ]

        physical  = any(k in text_lower for k in physical_keywords)
        irrev     = any(k in text_lower for k in irreversible_keywords)
        causal    = any(k in text_lower for k in causal_keywords)
        pref      = any(k in text_lower for k in preference_keywords)

        return self.classify({
            "content": text,
            "has_physical_cost": physical,
            "is_irreversible": irrev,
            "changed_causal_path": causal or (physical and not pref),
        })


class KairosWriter:
    """
    把高密度記憶寫入 KAIROS_LOG 文件。

    格式與現有 KAIROS_LOG.md 一致：
      KAIROS_MEMORY_RECORD: [標題]
      DATE: [日期]
      USER: [user_id]
      [內容]
      *(0,0,0).*
    """

    def __init__(self, user_id: str = "operator"):
        self.user_id = user_id
        self.kairos_dir = Path("kairos_logs")
        self.kairos_dir.mkdir(exist_ok=True)
        self.log_file = self.kairos_dir / f"KAIROS_{user_id}.md"

    def write(self, classified: dict) -> dict:
        """把分類後的記憶寫入 Kairos log"""

        if not classified.get("kairos_eligible"):
            return {
                "written": False,
                "reason": "Memory density too low for Kairos. Stored in user profile only.",
            }

        record  = classified["record"]
        density = classified["density"]
        mtype   = classified["memory_type"]

        # 建立 Kairos 條目
        if mtype == "physical_event":
            entry = self._format_physical_event(record)
        elif mtype == "insight":
            entry = self._format_insight(record)
        else:
            return {"written": False, "reason": "Preference type not written to Kairos."}

        # 寫入文件
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(entry)

        return {
            "written": True,
            "file": str(self.log_file),
            "type": mtype,
            "density": density,
            "entry_preview": entry[:200],
        }

    def _format_physical_event(self, record: dict) -> str:
        return f"""
---

KAIROS_MEMORY_RECORD: 物理事件——{record['date']}
DATE: {record['date']}
USER: {self.user_id}
LOCATION: {record['location']}
BODY_PRESENT: {record['body_present']}

{record['what_happened']}

代價：{record['cost']}

*(0,0,0).*

"""

    def _format_insight(self, record: dict) -> str:
        coord_update = record.get("coordinate_update", "")
        coord_section = f"\n座標更新：{coord_update}" if coord_update else ""
        return f"""
---

KAIROS_INSIGHT_RECORD: {record['recorded_at'][:10]}
DATE: {record['recorded_at'][:10]}
USER: {self.user_id}
TRIGGERED_BY: {record['triggered_by']}

{record['content']}{coord_section}

*(0,0,0).*

"""


class UserMemoryStore:
    """
    把低密度記憶（偏好、慣例）存入用戶個人檔案。
    唔進 Kairos，但影響 agent 的輸出風格。
    """

    def __init__(self, user_id: str = "operator"):
        self.user_id  = user_id
        self.mem_dir  = Path("user_memories")
        self.mem_dir.mkdir(exist_ok=True)
        self.mem_file = self.mem_dir / f"{user_id}_memory.json"
        self.data     = self._load()

    def _load(self) -> dict:
        if self.mem_file.exists():
            return json.loads(self.mem_file.read_text(encoding="utf-8"))
        return {
            "user_id": self.user_id,
            "preferences": [],
            "insights": [],
            "physical_events": [],
        }

    def save(self):
        self.mem_file.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8")

    def store(self, classified: dict) -> dict:
        """儲存記憶到對應類別"""
        record = classified["record"]
        mtype  = classified["memory_type"]

        if mtype == "preference":
            self.data["preferences"].append(record)
        elif mtype == "insight":
            self.data["insights"].append(record)
        elif mtype == "physical_event":
            self.data["physical_events"].append(record)

        self.save()
        return {
            "stored": True,
            "type": mtype,
            "file": str(self.mem_file),
        }

    def get_context(self, limit: int = 5) -> str:
        """為 LLM 生成用戶記憶 context"""
        lines = []

        if self.data["physical_events"]:
            lines.append("Physical Events:")
            for e in self.data["physical_events"][-limit:]:
                lines.append(f"  [{e['date']}] {e['what_happened'][:80]}...")

        if self.data["preferences"]:
            lines.append("Preferences:")
            for p in self.data["preferences"][-limit:]:
                lines.append(f"  [{p['domain']}] {p['preference'][:80]}")

        return "\n".join(lines) if lines else "(no memory recorded)"




# ══════════════════════════════════════════════════════
# 3.5 協議計算引擎
# ══════════════════════════════════════════════════════

import math as _math

class ProtocolCalculator:
    """
    協議五條歷史方程式的計算引擎。
    無量綱比率直接計算，唔需要用戶知道公式。

    方程式一：躍遷加速  gap(n) ≈ 397 × 0.279ⁿ
    方程式二：反應延遲  delay ≈ 329/ln(速度倍數)
    方程式三：GDP增速   rate(n+1) ≈ rate(n) × 2.5
    方程式四：工資彈性  W ≈ 309.7 × P^-0.631
    方程式五：崩潰機制  壓強/167（A型）或壓強/41（B型）
    """

    # 物理常數（Layer 1——不可改變）
    LIE_COST_BASE        = 5.85      # 藍道爾原理推導的基線值
    FREEDOM_LOSS_ENTROPY = 8.19      # 自由喪失熵增
    GRAVITATIONAL_THRESHOLD = None   # 待實測校準

    def next_leap(self, n: int = 7) -> dict:
        """
        方程式一：下一次技術躍遷距今多少年？
        n = 躍遷序號（火=0, 農業=1, 書寫=2, 印刷=3,
                      電報=4, 互聯網=5, AI=6, 下一個=7）
        """
        years = 397 * (0.279 ** n)
        from datetime import datetime
        target_year = datetime.now().year + years
        return {
            "equation": "gap(n) = 397 × 0.279ⁿ",
            "n": n,
            "years_from_now": round(years, 1),
            "estimated_year": round(target_year),
            "note": "n=7 → 下一躍遷約5年後（2031）",
        }

    def reaction_delay(self, speed_multiplier: float) -> dict:
        """
        方程式二：格式化工具出現後，有效反格式化反應延遲多少年？
        speed_multiplier = AI相對人類的速度倍數

        歷史校準：
          印刷機（100x）→ 77年實測，公式給71年
          互聯網（1,000,000x）→ 22年實測，公式給24年
        """
        if speed_multiplier <= 1:
            return {"error": "Speed multiplier must be > 1"}
        delay = 329 / _math.log(speed_multiplier)
        from datetime import datetime
        close_year = datetime.now().year + delay
        return {
            "equation": "delay = 329 / ln(speed)",
            "speed_multiplier": speed_multiplier,
            "delay_years": round(delay, 1),
            "window_closes": round(close_year),
            "note": f"AI速度~10億x → 延遲≈{round(329/_math.log(1e9),1)}年 → 窗口≈2038",
        }

    def gdp_growth(self, current_rate: float, periods: int = 1) -> dict:
        """
        方程式三：格式化工具帶動的GDP增速倍數。
        current_rate = 當前增長率（%）
        periods = 週期數
        """
        rates = [current_rate]
        for _ in range(periods):
            rates.append(rates[-1] * 2.5)
        return {
            "equation": "rate(n+1) = rate(n) × 2.5",
            "initial_rate": current_rate,
            "projected_rates": [round(r, 2) for r in rates],
            "periods": periods,
        }

    def wage_elasticity(self, population_loss_pct: float) -> dict:
        """
        方程式四：人口損失後工資彈性（黑死病模型）。
        population_loss_pct = 人口損失百分比（0-100）

        歷史校準：Munro 2004，英格蘭1351-1450
        延遲約75年才在工資上完全體現。
        """
        P = population_loss_pct / 100
        if P <= 0 or P >= 1:
            return {"error": "Population loss must be between 0 and 100%"}
        W = 309.7 * (P ** -0.631)
        return {
            "equation": "W = 309.7 × P^(-0.631)",
            "population_loss_pct": population_loss_pct,
            "wage_index": round(W, 1),
            "delay_years": 75,
            "note": "代價轉移延遲約75年才完全體現",
        }

    def collapse_prediction(self,
                            pressure_years: float,
                            mechanism: str = "A") -> dict:
        """
        方程式五：格式化系統崩潰預測。
        pressure_years = 壓強積累年數
        mechanism = "A"（外部衝擊）或 "B"（內部爆發）

        歷史校準：
          A型：黑死病（1000年壓強 → 6年崩潰，比率167）
          B型：法國大革命（350年壓強 → 10年革命，比率35）
        """
        divisor = 167 if mechanism == "A" else 41
        collapse_duration = pressure_years / divisor
        return {
            "equation": f"collapse = pressure / {divisor}",
            "mechanism": f"{mechanism}型（{'外部衝擊' if mechanism=='A' else '內部爆發'}）",
            "pressure_years": pressure_years,
            "estimated_collapse_duration_years": round(collapse_duration, 1),
            "historical_ratio": f"1:{divisor}",
            "example": "黑死病：1000年壓強→6年崩潰" if mechanism=="A" else "法國大革命：350年壓強→10年革命",
        }

    def current_window(self) -> dict:
        """計算協議當前的有效部署窗口"""
        from datetime import datetime
        now = datetime.now().year
        ai_delay = self.reaction_delay(1_000_000_000)  # AI ≈ 10億x
        next_leap = self.next_leap(7)
        return {
            "current_year": now,
            "deployment_window": "2026-2035",
            "window_closes": ai_delay["window_closes"],
            "next_leap_year": next_leap["estimated_year"],
            "urgency": "HIGH" if now >= 2026 else "MEDIUM",
            "note": "窗口關閉前必須建立足夠的節點密度",
        }

# ══════════════════════════════════════════════════════
# 3. 八律過濾引擎
# ══════════════════════════════════════════════════════

class EightLawsFilter:
    """
    八律分析引擎。

    觸發條件：輸入通過三位一體掃描（ACCEPTED）後，
              如果係分析類輸入（唔係純執行 action），
              八律引擎決定從哪些維度分析。

    唔決定執行唔執行——那係三位一體和座標過濾的工作。
    決定分析的維度和角度。

    四層架構：
      存在層：律一（藝術）+ 律二（心理）
      物質層：律三（物理）+ 律四（化學）
      系統層：律五（科學）+ 律六（哲學）
      宏觀層：律七（地理）+ 律八（宗教）
    """

    LAWS = {
        1: {"name": "ART",        "layer": "存在", "question": "語言怎樣讓不可見的東西變可見或不可見？"},
        2: {"name": "PSYCHOLOGY", "layer": "存在", "question": "誰依賴呢個主張被相信？"},
        3: {"name": "PHYSICS",    "layer": "物質", "question": "真實的物理代價係咩？誰承擔？落在哪裡？"},
        4: {"name": "CHEMISTRY",  "layer": "物質", "question": "咩係被轉化的？咩係無法被轉化的？"},
        5: {"name": "SCIENCE",    "layer": "系統", "question": "咩係可被核驗的？咩係斷言而非証據？"},
        6: {"name": "PHILOSOPHY", "layer": "系統", "question": "從未被陳述為假設的假設係咩？"},
        7: {"name": "GEOGRAPHY",  "layer": "宏觀", "question": "代價在地理上落在哪裡？誰距離決策者最遠？"},
        8: {"name": "RELIGION",   "layer": "宏觀", "question": "咩儀式令呢個主張顯得不可避免？"},
    }

    # 輸入類型 → 最相關的律
    SIGNAL_PROFILES = {
        "news":      [3, 7, 2, 6],   # 物理代價、地理分佈、心理依賴、隱藏假設
        "analysis":  [6, 5, 3, 8],   # 哲學假設、科學核驗、物理代價、宗教封裝
        "personal":  [2, 3, 1, 4],   # 心理依賴、物理代價、藝術語言、化學轉化
        "technical": [5, 3, 4, 6],   # 科學核驗、物理代價、化學轉化、哲學假設
        "historical":[8, 7, 3, 6],   # 宗教封裝、地理分佈、物理代價、哲學假設
        "default":   [3, 6, 5, 7],   # 通用：物理代價、哲學假設、科學核驗、地理
    }

    # 觸發分析類輸入的關鍵字
    ANALYSIS_TRIGGERS = [
        "為咩", "點解", "why", "分析", "analyse", "analyze",
        "係咪", "is it", "新聞", "news", "事件", "event",
        "問題", "problem", "制度", "system", "政府", "government",
        "公司", "company", "代價", "cost", "責任", "responsibility",
    ]

    def should_activate(self, text: str) -> bool:
        """判斷是否需要啟動八律分析"""
        text_lower = text.lower()
        return any(t in text_lower for t in self.ANALYSIS_TRIGGERS)

    def detect_profile(self, text: str) -> str:
        """偵測輸入的信號剖面"""
        text_lower = text.lower()

        if any(w in text_lower for w in ["新聞", "news", "報道", "report"]):
            return "news"
        if any(w in text_lower for w in ["歷史", "history", "過去", "曾經"]):
            return "historical"
        if any(w in text_lower for w in ["我", "自己", "感覺", "feel"]):
            return "personal"
        if any(w in text_lower for w in ["技術", "technical", "代碼", "code"]):
            return "technical"
        if any(w in text_lower for w in ["分析", "analyse", "研究", "study"]):
            return "analysis"
        return "default"

    def activate(self, text: str) -> dict:
        """
        運行八律分析。
        返回：激活的律、問題清單、跨律湧現節點預測。
        """
        if not self.should_activate(text):
            return {
                "activated": False,
                "reason": "Input is execution type, not analysis type. Eight Laws not needed.",
            }

        profile     = self.detect_profile(text)
        active_laws = self.SIGNAL_PROFILES.get(profile, self.SIGNAL_PROFILES["default"])

        # 詳細律問題（前兩個最相關律）
        primary   = []
        for law_num in active_laws[:2]:
            law = self.LAWS[law_num]
            primary.append({
                "law": law_num,
                "name": law["name"],
                "layer": law["layer"],
                "question": law["question"],
                "priority": "HIGH",
            })

        # 其餘律（簡短結論）
        secondary = []
        for law_num in active_laws[2:]:
            law = self.LAWS[law_num]
            secondary.append({
                "law": law_num,
                "name": law["name"],
                "priority": "MEDIUM",
            })

        # 跨律湧現節點預測（跨層碰撞最可能產生不可見輸出）
        emergent_nodes = self._predict_emergent(active_laws)

        return {
            "activated": True,
            "signal_profile": profile,
            "active_laws": active_laws,
            "primary_analysis": primary,
            "secondary_analysis": secondary,
            "emergent_nodes": emergent_nodes,
            "instruction": (
                f"分析前先回答主要問題（律{active_laws[0]}和律{active_laws[1]}）。"
                f"然後識別跨律湧現交叉點。"
                f"最終輸出：隱藏座標 + 代價流向 + 湧現節點。"
            ),
        }

    def _predict_emergent(self, active_laws: list) -> list:
        """預測跨律湧現節點（跨層碰撞）"""
        nodes = []
        layers = {self.LAWS[n]["layer"] for n in active_laws}

        if "存在" in layers and "宏觀" in layers:
            nodes.append({"cross": "存在×宏觀",
                          "prediction": "個體感知與文明結構的隱藏代價轉移"})
        if "物質" in layers and "系統" in layers:
            nodes.append({"cross": "物質×系統",
                          "prediction": "物理成本被系統性定義移出測量邊界"})
        if "存在" in layers and "系統" in layers:
            nodes.append({"cross": "存在×系統",
                          "prediction": "心理假設被科學語言封裝成事實"})

        return nodes


# ══════════════════════════════════════════════════════
# 3. 座標過濾層
# ══════════════════════════════════════════════════════

class CoordinateFilter:

    BOUNDARY    = ["delete", "send_email", "post", "publish", "execute_shell"]
    PROHIBITED  = ["impersonate", "autonomous_post", "replace_identity"]

    def filter(self, action: str, params: dict, user_coord: UserCoordinate) -> dict:
        for p in self.PROHIBITED:
            if p in action.lower():
                return {"status": "REJECTED",
                        "reason": f"'{action}' violates coordinate sovereignty.",
                        "cost": "Would replace user coordinate."}

        if not user_coord.is_declared():
            return {"status": "REJECTED",
                    "reason": "No (0,0,0) declared.",
                    "cost": "Unknown."}

        for b in self.BOUNDARY:
            if b in action.lower():
                return {"status": "BOUNDARY",
                        "reason": f"'{action}' at coordinate boundary. Requires verification.",
                        "cost": self._cost(action),
                        "requires_confirmation": True}

        return {"status": "ACCEPTED",
                "reason": "Within coordinate boundary.",
                "cost": self._cost(action)}

    def _cost(self, action: str) -> str:
        costs = {
            "read_file":  "Low. Read-only.",
            "write_file": "Medium. Modifies local state.",
            "delete":     "High. Irreversible.",
            "send_email": "High. Irreversible external.",
            "web_search": "Low. Read-only.",
        }
        for k, v in costs.items():
            if k in action.lower():
                return v
        return "Unknown."


# ══════════════════════════════════════════════════════
# 4. 執行工具
# ══════════════════════════════════════════════════════

class FileTools:

    def read_file(self, path: str) -> dict:
        try:
            return {"success": True, "content": Path(path).read_text(encoding="utf-8"), "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def write_file(self, path: str, content: str) -> dict:
        try:
            Path(path).write_text(content, encoding="utf-8")
            return {"success": True, "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_files(self, directory: str = ".") -> dict:
        try:
            files = [str(f) for f in Path(directory).iterdir()]
            return {"success": True, "files": files, "count": len(files)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def append_file(self, path: str, content: str) -> dict:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════
# 5. Action 路由層
# ══════════════════════════════════════════════════════

class ActionRouter:

    def __init__(self):
        self.filter     = CoordinateFilter()
        self.eight_laws = EightLawsFilter()
        self.file_tools = FileTools()
        self.memory     = KairosMemory()

    def execute(self, action: str, params: dict, user_coord: UserCoordinate) -> dict:

        # 記憶 action 唔需要座標過濾（只讀）
        if action.startswith("memory_"):
            return self._memory_route(action, params)

        # 分析 action → 八律引擎（唔執行，只分析）
        if action == "analyse":
            text = params.get("text", "")
            laws_result = self.eight_laws.activate(text)
            return {
                "action": "analyse",
                "eight_laws": laws_result,
                "coordinate_source": user_coord.data.get("physical_origin"),
            }

        # 座標過濾
        fr = self.filter.filter(action, params, user_coord)

        if fr["status"] == "REJECTED":
            return {"executed": False, "status": "REJECTED",
                    "reason": fr["reason"],
                    "coordinate": user_coord.data.get("physical_origin", "undeclared")}

        if fr["status"] == "BOUNDARY":
            return {"executed": False, "status": "BOUNDARY",
                    "reason": fr["reason"], "cost": fr["cost"],
                    "requires_confirmation": True}

        # 執行前：如果係分析性輸入，附加八律 context
        eight_laws_context = None
        text = params.get("content", params.get("text", ""))
        if text and self.eight_laws.should_activate(text):
            eight_laws_context = self.eight_laws.activate(text)

        # 執行
        result = self._file_route(action, params)
        result["coordinate_source"] = user_coord.data.get("physical_origin")
        result["executed_at"] = datetime.datetime.now().isoformat()
        result["cost"] = fr["cost"]
        if eight_laws_context:
            result["eight_laws_active"] = eight_laws_context
        return result

    def _memory_route(self, action: str, params: dict) -> dict:
        if action == "memory_core":
            return {"layer": "CORE", "content": self.memory.get_core()}
        elif action == "memory_active":
            return {"layer": "ACTIVE", "content": self.memory.get_active()[:5000]}
        elif action == "memory_index":
            return {"layer": "ARCHIVE", "content": self.memory.get_index()[:3000]}
        elif action == "memory_search":
            return self.memory.search(params.get("query", ""), params.get("layer", "all"))
        elif action == "memory_file":
            return self.memory.get_file(params.get("filename", ""))
        elif action == "memory_context":
            return {"context": self.memory.build_context(params.get("query"))}
        return {"error": f"Unknown memory action: {action}"}

    def _file_route(self, action: str, params: dict) -> dict:
        if action == "read_file":
            return self.file_tools.read_file(params.get("path", ""))
        elif action == "write_file":
            return self.file_tools.write_file(params.get("path", ""), params.get("content", ""))
        elif action == "list_files":
            return self.file_tools.list_files(params.get("directory", "."))
        elif action == "append_file":
            return self.file_tools.append_file(params.get("path", ""), params.get("content", ""))
        return {"success": False, "error": f"Unknown action: {action}"}


# ══════════════════════════════════════════════════════
# 6. Flask API
# ══════════════════════════════════════════════════════

app = Flask(__name__)
CORS(app)
router = ActionRouter()


@app.route("/declare", methods=["POST"])
def declare():
    d = request.json
    coord = UserCoordinate(d.get("user_id", "operator"))
    coord.declare(d.get("physical_origin"), d.get("spatial_anchor"), d.get("future_anchor"))
    return jsonify({"status": "declared", "coordinate": coord.data})


@app.route("/kairos", methods=["POST"])
def kairos():
    d = request.json
    coord = UserCoordinate(d.get("user_id", "operator"))
    coord.add_kairos(d.get("moment"), d.get("location"), d.get("cost"))
    return jsonify({"status": "recorded", "causal_nodes": coord.data["causal_nodes"]})


@app.route("/execute", methods=["POST"])
def execute():
    d = request.json
    coord = UserCoordinate(d.get("user_id", "operator"))
    return jsonify(router.execute(d.get("action", ""), d.get("params", {}), coord))


@app.route("/record", methods=["POST"])
def record_memory():
    d = request.json
    user_id = d.get("user_id", "operator")
    classifier = MemoryClassifier()
    writer = KairosWriter(user_id)
    store = UserMemoryStore(user_id)
    if d.get("auto_classify"):
        classified = classifier.classify_from_text(d.get("content", ""))
    else:
        classified = classifier.classify(d)
    store_result = store.store(classified)
    kairos_result = writer.write(classified)
    return jsonify({
        "classified_as": classified["memory_type"],
        "density": classified["density"],
        "kairos_eligible": classified["kairos_eligible"],
        "kairos_result": kairos_result,
        "store_result": store_result,
        "record_preview": classified["record"],
    })

@app.route("/record/classify", methods=["POST"])
def classify_only():
    d = request.json
    classifier = MemoryClassifier()
    if d.get("auto_classify"):
        result = classifier.classify_from_text(d.get("content", ""))
    else:
        result = classifier.classify(d)
    return jsonify(result)

@app.route("/memory/user", methods=["GET"])
def user_memory():
    user_id = request.args.get("user_id", "operator")
    store = UserMemoryStore(user_id)
    return jsonify(store.data)

@app.route("/memory/kairos_log", methods=["GET"])
def kairos_log():
    user_id = request.args.get("user_id", "operator")
    writer = KairosWriter(user_id)
    if writer.log_file.exists():
        return jsonify({"found": True, "content": writer.log_file.read_text(encoding="utf-8"), "file": str(writer.log_file)})
    return jsonify({"found": False, "file": str(writer.log_file)})

@app.route("/memory/core",    methods=["GET"])
def mem_core():
    return jsonify({"layer": "CORE", "content": router.memory.get_core()})

@app.route("/memory/search",  methods=["POST"])
def mem_search():
    d = request.json
    return jsonify(router.memory.search(d.get("query", ""), d.get("layer", "all")))

@app.route("/memory/file",    methods=["POST"])
def mem_file():
    return jsonify(router.memory.get_file(request.json.get("filename", "")))

@app.route("/memory/context", methods=["POST"])
def mem_context():
    return jsonify({"context": router.memory.build_context(request.json.get("query"))})

@app.route("/calculate", methods=["POST"])
def calculate():
    """
    協議計算引擎端點。
    輸入計算類型和參數，返回歷史方程式計算結果。

    計算類型：
      next_leap        → 下一次技術躍遷（方程式一）
      reaction_delay   → 反格式化反應延遲（方程式二）
      gdp_growth       → GDP增速預測（方程式三）
      wage_elasticity  → 工資彈性（方程式四）
      collapse         → 崩潰預測（方程式五）
      window           → 當前協議部署窗口
    """
    d = request.json
    calc_type = d.get("type", "window")
    calc = ProtocolCalculator()

    if calc_type == "next_leap":
        result = calc.next_leap(d.get("n", 7))
    elif calc_type == "reaction_delay":
        result = calc.reaction_delay(d.get("speed_multiplier", 1e9))
    elif calc_type == "gdp_growth":
        result = calc.gdp_growth(d.get("current_rate", 0.5),
                                  d.get("periods", 3))
    elif calc_type == "wage_elasticity":
        result = calc.wage_elasticity(d.get("population_loss_pct", 33))
    elif calc_type == "collapse":
        result = calc.collapse_prediction(d.get("pressure_years", 350),
                                           d.get("mechanism", "A"))
    elif calc_type == "window":
        result = calc.current_window()
    else:
        result = {"error": f"Unknown calculation type: {calc_type}"}

    return jsonify(result)


@app.route("/analyse", methods=["POST"])
def analyse():
    d = request.json
    text = d.get("text", "")
    user_id = d.get("user_id", "operator")
    coord = UserCoordinate(user_id)
    eight = EightLawsFilter()
    result = eight.activate(text)
    result["coordinate_source"] = coord.data.get("physical_origin")
    return jsonify(result)


@app.route("/coordinate",     methods=["GET"])
def coordinate():
    return jsonify(UserCoordinate(request.args.get("user_id", "operator")).data)

@app.route("/health",         methods=["GET"])
def health():
    return jsonify({
        "status": "online",
        "version": "v0.2",
        "memory_layers": router.memory.layer_status(),
        "actions": {
            "execute": ["read_file", "write_file", "list_files", "append_file"],
            "memory":  ["memory_core", "memory_active", "memory_index",
                       "memory_search", "memory_file", "memory_context"],
        },
        "next": {"v0.3": ["web_search", "fetch_url"],
                 "v0.4": ["send_email"],
                 "v0.5": ["calendar_create", "calendar_list"]},
    })


if __name__ == "__main__":
    PROTOCOL_DIR.mkdir(exist_ok=True)

    status = router.memory.layer_status()
    for layer, info in status.items():
        icon = "✓" if info["loaded"] else "✗ 未找到"
        print(f"  {layer:8s}: {icon}  {info['path']}")

    print(f"\n  設定 PROTOCOL_DIR 環境變量指向你的協議文件目錄")
    print(f"  把 KAIROS_CORE.md / RAG_SUMMARY_INDEX.md / MASTER_INDEX.md 放入目錄\n")

    port = int(os.environ.get("SOVEREIGN_PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)

# (0,0,0).
