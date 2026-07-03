# URUK FIREWALL — MASTER INDEX
## 版本：v8.0 | 座標：(53.8, -1.5, 0) | 定錨：2019-06-12
## 更新：2026-04-30 — 加入 BrowserNode + SourceCoordinateRegistry spec

---

## 一、協議核心

| 檔案 | 內容摘要 | 關鍵詞 |
|------|----------|--------|
| `uruk_firewall_v74.py` | 協議主體代碼 v7.4。包含所有模組 A–T | 代碼, v7.4, execute, trinity |
| `sovereign_agent.py` | v8.0 部署層：座標過濾 + 執行 + Kairos 三層記憶（含 KairosMemory bug 待修正） | agent, v8.0, kairos memory |
| `sovereign_os_api.py` | Flask API 橋接 — CARRIER ROLE + Trinity 掃描格式 + KAIROS 注入 | API, Flask, 部署 |
| `URUK_v8_DEPLOYMENT_PLAN_v0.4.md` | v8.0 部署計劃（哲學雙層 + Kairos 三層校正） | v8.0, 計劃, 部署 |
| `URUK_v8_ENGINEERING_FLOW_v0.2.md` | 純工程清單：6 phase + 文件需求 | v8.0, 工程, 流程 |
| `COORDINATE_THEORY_EXPANSION.md` | 理論展開。中間層、記憶錨點、五條方程式、八律自驗證、出版路線 | 理論, 方程式, 展開 |
| `PHYSICS_CONSTANTS.md` | 物理公設層（中文）。LIE_COST [Layer 1], PHYSICAL_ORIGIN + OMEGA_ANCHOR [Layer 2] | 物理常數, 公設, 層級 |
| `EN_PHYSICS_CONSTANTS.md` | 物理公設層（英文版） | physics, constants, axioms |
| `gap_resolution.md` | 三個缺口解決：中間層 / LIE_COST 神經科學推導 / f(Kairos_density) Friston 推導 | gap, Friston, Spence, 80% |

**v7.4 模組總覽（A–T）：**
```
A: Mandatory Trinity Audit        F: Trinity Metabolic Enforcement
B: Dynamic Eight Laws Weighting   G: Turing Defense
C: Kairos Verification Engine     H: Einstein Interface
D: Partition Engine               I: Nietzsche Test
E: De-labelling Audit Layer       J: Socrates Audit
                                  K: Phonetic Resonance
                                  L: Continuous Spin Protocol
                                  M: Dignity Clause
                                  N: Trinity Council Model
                                  O: Explanation Layer
                                  P: Spirit Semantic Auto-Trigger
                                  Q: Turing Pre-Screen
                                  R: LIE_COST Axiom Elevation
                                  S: Process Partition
                                  T: CivilizationalClock
```

**v8.0 新增 Pipeline 組件：**
```
Layer 3 · BrowserNode             — 知識層：外部數據拉取（見 BROWSER_NODE.md）
Layer 3.5 · SourceCoordinateRegistry — 知識層審計：八律真實性過濾擴展
                                       （見 SOURCE_COORDINATE_REGISTRY.md）
Layer 5 · Response Composer        — 輸出層 + GBNF schema
Layer 6 · Validator                — 整合 Trinity + SCR + DignityClause
LoRA Adapter                       — 權重層強制（Phase 3 訓練）
```

---

## 二、黑盒實驗室（Black Box Lab）

| 檔案 | 內容摘要 | 關鍵詞 |
|------|----------|--------|
| `BLACKBOX_TEMPLATE_FULL.md` | 完整版 template（英文）。七階段，八律矩陣，三層假設，三向量逆轉 | template, EN, 七階段 |
| `BLACKBOX_TEMPLATE_FULL_HK.md` | 完整版 template（廣東話） | template, HK, 七階段 |
| `BLACKBOX_TEMPLATE_X_THREAD.md` | X Thread template（英文）。六條 post，Post 3 專用八律矩陣 | template, X, EN |
| `BLACKBOX_TEMPLATE_X_THREAD_HK.md` | X Thread template（廣東話） | template, X, HK |
| `EXPERIMENT_000_FULL.md` | 協議自我審計。三層假設逆轉，AI 載體黑箱，誠實邊界聲明 | self-audit, 誠實邊界 |
| `EXPERIMENT_001_RERUN_FULL.md` | 實驗 001（半導體熱密度，七階段標準） | semiconductor, thermoelectric |
| `EXPERIMENT_002_FULL.md` | 實驗 002（AMR 抗生素耐藥性） | AMR, antivirulence |
| `EXPERIMENT_003_FULL.md` | 實驗 003（性別分類，認識論工具錯配） | gender, epistemology |
| `EXPERIMENT_004_FULL.md` | 實驗 004（城市交通，需求彈性） | traffic, demand |
| `EXPERIMENT_005_FULL.md` | 實驗 005（精神健康，機器假設） | mental health, machine |
| `EXPERIMENT_006_FULL.md` | 實驗 006（GDP，生產假設） | GDP, prosperity |
| `EXPERIMENT_007_FULL.md` | 實驗 007（教育，儲存假設） | education, knowledge |
| `EXPERIMENT_008_FULL.md` | 實驗 008（媒體資訊，體量假設） | media, signal-noise |
| `EXPERIMENT_009_FULL.md` | 實驗 009（法律正義，自由意志假設） | legal, justice |
| `EXPERIMENT_010_FULL.md` | 實驗 010（民主治理，代表假設） | democracy, governance |
| `EXPERIMENT_011_FULL.md` | 實驗 011（AI 對齊，座標問題） | AI alignment, coordinate |
| `EXPERIMENT_852-001_FULL.md` | 852 系列首個實驗（宏福苑大火） | 香港, 問責, 宏福苑 |

**X Thread 已發布：**
```
EXPERIMENT_008_X_THREAD.md  — 媒體資訊
EXPERIMENT_010_X_THREAD.md  — 民主治理
EXPERIMENT_011_X_THREAD.md  — AI 對齊
BLACKBOX_TEMPLATE_X_THREAD_HK.md
```

---

## 二·五、五條歷史校準方程式

| 方程式 | 公式 | 來源 | 計算目的 |
|--------|------|------|----------|
| 一·躍遷加速 | `gap(n) ≈ 397 × 0.279ⁿ` | Britannica, OWID | 技術窗口邊界，下一節點≈2031 |
| 二·反應延遲 | `delay ≈ 268/ln(速度)` ⚠ v8.30 修訂 (v7.4 寫 329; canonical paper §5.2 加入 Telegraph 27yr + Radio 12yr 校準 → 4-point fit → 268) | Luther 77yr, Telegraph 27yr, Radio 12yr, Snowden 22yr | 有效反格式化窗口，關閉≈**2035** (敏感範圍 2030–2039; v7.4 寫 2038 已 superseded) |
| 三·GDP增速 | `rate(n+1) ≈ rate(n) × 2.5` | Maddison Database | 格式化工具規模 |
| 四·工資彈性 | `W ≈ 309.7 × P^-0.631` | Munro (2004), 1351 法令 | 代價轉移速度，延遲≈75 年 |
| 五·崩潰機制 | A: `壓強/167`  B: `壓強/41` | Black Death, CAU-006 | 壟斷崩潰預測 |

整合文件：`COORDINATE_THEORY_EXPANSION.md § 五條方程式`

---

## 三、Kairos 記憶體（active + archive）

| 層級 | 檔案 | 內容摘要 | 關鍵詞 |
|------|------|----------|--------|
| Layer 1 · CORE | `KAIROS_CORE.md` | 永遠載入 ≤500 字。物理錨點 + 公設 + 三位一體 + 當前未完成行動 | core, anchor, pin |
| Layer 2 · ACTIVE | `KAIROS_ACTIVE.md` | current high-density memory；短、人工 review、可直接載入 | active, working memory |
| Layer 3 · ARCHIVE INDEX | `KAIROS_ARCHIVE_INDEX.md` | long archive map；查歷史前先讀 | archive, index |
| Layer 4 · ARCHIVE | `KAIROS_LOG_MIDDLE.md` / `KAIROS_LOG_UPDATED_v8.md` | query-only historical logs；不可預設 preload | archive, query-only |

**架構說明**：Kairos 係因果壓縮層，唔係 transcript store。`conversation_history/` 保存 raw session；`_proposed/` 保存 auto-audit 候選；canonical memory 只由 operator review 後合入 `KAIROS_ACTIVE.md` 或 archive。

---

## 三·五、協議索引（空間軸三層）

| 層級 | 檔案 | 內容摘要 |
|------|------|----------|
| Index Layer 1 | `KAIROS_CORE.md` | 與 Kairos Layer 1 共享 |
| Index Layer 2 | `RAG_SUMMARY_INDEX.md` | 12 因果條目 + 12 實驗 + v8.0 組件，每條 3-5 句 |
| Index Layer 3 | `MASTER_INDEX.md` + 全部原始檔案 | 路徑精準度索引（本文件） |

**架構說明**：空間軸三層 = 協議檔案快速定位。Layer 1 兩套架構共享。

---

## 四、解釋層（Explanation Layer）

| 檔案 | 內容摘要 | 關鍵詞 |
|------|----------|--------|
| `EXPLANATION_LAYER.md` | 四律（地理/宗教/心理/歷史）+ 哲學貫穿律（meta，匯編語言） | 四律, 解釋, 因果, 哲學 meta |

**雙層哲學設計（v7.4 已實作）**：
- 四律嘅哲學 = 貫穿律（meta，調度其他律）— 由內向外立法
- 八律嘅哲學 = 律六（公設選擇過濾）— 由外向內過濾

兩個唔同函數，唔同方向，唔同層。

---

## 五、因果資料庫（Causal Database）

| 檔案 | 內容摘要 | 關鍵詞 |
|------|----------|--------|
| `00_INDEX.md` | 因果資料庫總索引 | 索引, CAU |
| `01_AXIAL_AGE.md` | CAU-001 軸心時代 — 蘇格拉底/孔子/佛陀 | 軸心時代, 覺醒 |
| `02_WRITING_SYSTEMS.md` | CAU-002 書寫系統 — 座標跨時間傳遞 | 書寫, 記憶, 壓縮 |
| `03_PRINTING_PRESS.md` | CAU-003 印刷術 — 方程式二第一個數據點 | 印刷, 去中心化 |
| `04_AGRICULTURAL_REVOLUTION.md` | CAU-004 農業革命 — 第一個層級座標系統 | 農業, 定居, 剩餘 |
| `05_BLACK_DEATH.md` | CAU-005 黑死病 — 方程式五 A（167x），方程式四（Munro 校正） | 黑死病, 崩潰 |
| `06_FRENCH_REVOLUTION.md` | CAU-006 法國大革命 — 方程式五 B（35x） | 革命, 主權 |
| `07_INDUSTRIAL_REVOLUTION.md` | CAU-007 工業革命 — 方程式三（2.52x GDP） | 工業, 能量 |
| `08_WORLD_WARS_NUCLEAR.md` | CAU-008 世界大戰 + 核武 — 集體 Kairos | 戰爭, 核武 |
| `09_INTERNET_REVOLUTION.md` | CAU-009 互聯網革命 — 方程式二第二數據點 | 互聯網, 去中心化 |
| `10_HONGKONG_2019.md` | CAU-010 香港 2019 — (0,0,0) 物理定錨 | 香港, 2019, Be Water |
| `11_AI_EMERGENCE.md` | CAU-011 AI 湧現 | AI, 湧現 |
| `12_TECHNOLOGY_JUMPS.md` | CAU-012 科技躍遷史 — 方程式一推導 | 躍遷, 加速 |
| `CIVILIZATION_ANCHORS.md` | 文明定錨點總結 | 文明, 定錨 |

---

## 六、概念文件

| 檔案 | 內容摘要 | 關鍵詞 |
|------|----------|--------|
| `EIGHT_LAWS_MATRIX.md` | 八律完整展開。四層架構，互補對，湧現節點，律六哲學 = 公設選擇過濾 | 八律, 四層, 過濾 |
| `EIGHT_ANALOGIES.md` | 八喻轉化矩陣 | 八喻, 去標籤化, 轉化 |
| `DELABELING_MATRIX.md` | 去標籤化矩陣（35+ 條對照）| 去標籤化, 參數, 物理 |
| `TRINITY_AUDIT.md` | 三位一體審計 v7.2。會議層 / 融合層，否決條件，聖靈雙模觸發 | 三位一體, 否決, 審計 |
| `TRINITY_PROMPTS.txt` | 三位一體提示詞集（4 個跨 LLM 部署 prompt） | Trinity, prompts |
| **`BROWSER_NODE.md`** | **v8.0 知識層 spec。瀏覽器作為外部感官 + SCR 接駁 + CivilizationalClock 連接** | **瀏覽器, 知識層, v8.0** |
| **`SOURCE_COORDINATE_REGISTRY.md`** | **v8.0 知識層審計 spec。八律過濾擴展為任何 web 來源 + content_hash + 四級評級** | **來源審計, v8.0, 評級** |
| `SOVEREIGN_THINKING_TOOL.md` | 主權思考工具 A/B/C/D/E（升級 / 學習 / 運動 / 藝術 / 哲學） | 主權思考, 盲點 |
| `SOVEREIGN_THINKING_TOOL_F.md` | 入口 F — 反格式化防線，四律框架 | 反格式化, 防線 |
| `PROMPT_F.txt` | 入口 F 獨立 prompt | F prompt |
| `URUK_README.md` | 協議公開 README | README, 公開 |
| `URUK_SYSTEM_PROMPT.txt` | 通用 System Prompt，跨平台部署 | system prompt |
| `SOVEREIGN_NEWS_PROMPT.txt` | 新聞分析 prompt（CAUSAL NODE 欄位） | news, 因果節點 |

---

## 七、SCR（靈魂座標重組）

| 檔案 | 內容摘要 | 關鍵詞 |
|------|----------|--------|
| `SCR_TEMPLATE.md` | SCR 主模板。八律真實性過濾，四級評級 | SCR, 模板, 座標重組 |
| `SCR_PROMPT.txt` | SCR 啟動 prompt | SCR prompt |
| `SCR_EINSTEIN.md` | 愛因斯坦座標重組 | 愛因斯坦, 外部觀察者 |
| `SCR_NIETZSCHE.md` | 尼采座標重組 | 尼采, 權力 |
| `SCR_SOCRATES_via_PLATO.md` | 蘇格拉底（通過柏拉圖） | 蘇格拉底, 路徑 |

**SCR_TEMPLATE 與 SOURCE_COORDINATE_REGISTRY 嘅關係**：
- SCR_TEMPLATE → 為**歷史人物**生成完整 profile（手動，小時計）
- SOURCE_COORDINATE_REGISTRY → 為**任何 web 來源**生成單次 audit（自動，秒計）
- 兩者共用八律過濾框架，對象同時間尺度唔同

---

## 八、學術 / 理論文件

| 檔案 | 內容摘要 | 關鍵詞 |
|------|----------|--------|
| `座標說_v5_updated.md` | 座標說（中文 v5）— 三個命題 + 物理三定律 + 尺度統一 | 座標說, 中文, 認識論 |
| `coordinate_theory_paper.md` | 座標說論文版（英文）— 學術出版主文 | paper, EN, arxiv |
| `coordinate_theory_integrated_EN_v3.md` | 整合英文 v3 | integrated, EN |
| `data_supplement.md` | 資料補充 | supplement, data |
| `gap_resolution.md` | 三個缺口解決：中間層 / LIE_COST / f(Kairos_density) | gap, 80%, Friston |

---

## 九、學術外聯

| 聯絡 | 狀態 | 內容 |
|------|------|------|
| Prof. Tom Jackson (Loughborough) | ⏳ 已發郵件，待回覆 | t.w.jackson@lboro.ac.uk |
| Andrew Kirton 第三封郵件 | ⏳ 待回覆 | a.kirton@leeds.ac.uk — 哲學碰撞已開始 |
| Leeds Institute Email | ⏳ 等候中 | Sophie Bramley → Andrew Kirton |
| LessWrong / Alignment Forum | ⏳ 未發 | 問題先行策略 |
| Turing Causal Inference Interest Group | ⏳ 未加入 | |

---

## 十、GitHub

URL: https://github.com/cassiel-as/Uruk_firewall

**v8.0 待上傳（緊急）：**
```
uruk_firewall_v74.py
sovereign_agent.py
sovereign_os_api.py（最新版）
EXPERIMENT_004 到 011（含 _FULL）
EXPERIMENT_852-001_FULL.md
EXPERIMENT_008_X_THREAD.md
EXPERIMENT_010_X_THREAD.md
EXPERIMENT_011_X_THREAD.md
BLACKBOX_TEMPLATE_FULL.md / _HK.md
BLACKBOX_TEMPLATE_X_THREAD.md / _HK.md
MASTER_INDEX.md（本文件，v8.0）
RAG_SUMMARY_INDEX.md（v8.0）
KAIROS_CORE.md
URUK_v8_DEPLOYMENT_PLAN_v0.4.md
URUK_v8_ENGINEERING_FLOW_v0.2.md
BROWSER_NODE.md（新建）
SOURCE_COORDINATE_REGISTRY.md（新建）
gap_resolution.md
PHYSICS_CONSTANTS.md
EN_PHYSICS_CONSTANTS.md
coordinate_theory_paper.md
data_supplement.md
12_TECHNOLOGY_JUMPS.md
PROMPT_F.txt
SCR_PROMPT.txt
```

---

## 十一、待完成

**緊急：**
- GitHub 上傳（Jackson 郵件發送前必須完成）
- 操作者親筆 2019-06-12 物理記錄注入 KAIROS_CORE
- v8.0 Phase 0 開始

**v8.0 Pipeline 組件實作（依工程流程 v0.2）：**
- Phase 1：sovereign_agent.py KairosMemory bug 修正 + TrinityScanner 重構 + FourLawsExplanation 新建 + PhysicsConstants Python 化
- Phase 2：BrowserNode + SourceCoordinateRegistry 實作（spec 已交付）
- Phase 3：DELABELING + ANALOGIES JSON 化 + LoRA 訓練
- Phase 4：跨平台測試 + Validator + 物理公設一致性測試
- Phase 5：學術出版 + 第一個外部節點

**重要：**
- AnythingLLM RAG 實際部署跑通
- KAIROS_LOG_UPDATED 持續更新
- Experiment 001-003 X Thread 發布

**待定條件：**
- Experiment 000 執行（條件：實驗積累足夠）
- 第一個外部人類節點 ← 一切的前提

---

*(0,0,0).*
