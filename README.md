# URUK TRINITY CONSOLE

> Knowledge-grounded LLM operating console for Trinity deliberation, output self-audit, harness replay, and controlled self-upgrade.
> 操作者：Cassiel_as | (53.8, -1.5, 0) | PHYSICAL_ORIGIN: 2019-06-12

---

## Current System Snapshot

URUK Trinity Console 而家唔係「另一個聊天 UI」。佢係一個本機 AI 工作流操作系統：

- **LLM 大腦層**：OpenAI / Anthropic / Gemini / Groq / Ollama / Claude Desktop / Codex Desktop / Windows Copilot 等 model backend。
- **知識操作層**：`data/` + RAG + knowledge manifest + coordinate cards，負責把座標說、CAU、KAIROS、protocol references 變成可查、可審計、可 trace 嘅知識底座。
- **Trinity 內部會議層**：Father / Son / Spirit / Council 照 `TRINITY_AUDIT v7.2` 運作；普通主回答只顯示融合後答案，完整三節點 trace 留喺「內部質控 / 完整流程」展開區。
- **輸出自查層**：`density_audit.py`、coordinate output eval、council decision、Son veto、Spirit interrupt metadata 針對系統輸出自查，唔係審判用戶本人。
- **Harness / replay 層**：每次 session 可保存 conversation markdown + machine-readable harness episode；`data/benchmarks/` + `tools/benchmark_runner.py` 提供 deterministic regression baseline。
- **Episode compare 層**：`tools/episode_compare.py` 可比較兩個 harness episode，檢查 coordinate score、knowledge trace、validator、node error 同 voice hash 變化。
- **Prompt regression 層**：`tools/prompt_regression_check.py` 追蹤 runtime prompt/protocol bundle hash，對比 baseline，並串起 benchmark / quick_eval / episode compare。
- **Task-aware local workers**：`services/local_model_router.py` 將分類、語言整理、視覺觀察、協議候選分配到不同本地模型；本地模型只做 bounded worker，真正推理、決策同最終權限會升級到大型模型。
- **推理預算層**：`services/inference_governor.py` 將路由估算轉成每次 request 嘅模型調用硬上限，實際記錄成功、失敗、failover、retry、獨立模型數同耗時；座標／抽象概念自動用 `protocol_compact`，由 Father + Spirit 兩次模型調用完成回答與輸出審計。
- **Self-upgrade 層**：`upgrade_engine.py` + relay protocol + custom tools，畀 Codex / Claude 設計升級，再由 URUK deterministic validator / installer / smoke test 執行。
- **Self-upgrade report 層**：`services/upgrade_report.py` + `tools/self_upgrade_report.py` 將最新升級計劃、upgrade log、硬閘、prompt regression 匯總成 JSON + Markdown 報告。

最新關鍵行為：

- 聖靈有兩條 interrupt 路徑：`SEMANTIC` 假設逆轉，`STOCHASTIC` runtime random gate；兩者觸發後都會重開會議。
- Pipeline 執行 topology 叫 `single_llm` / `multi_llm`，唔再同聖靈 Mode A / Mode B 混名。
- 用戶輸入被視為 `signal / claim / task / context`；審計目標係系統輸出、知識使用同回應路徑。

---

## Component README Map

新讀者建議順序：

| 要理解 | 入口 |
|---|---|
| 系統整體、運行方式、市場定位 | `README.md` |
| 文件索引、模型 onboarding、docs 規則 | [`docs/README.md`](docs/README.md) |
| Runtime prompt、nodes.yaml、protocol references | [`config/README.md`](config/README.md) |
| Python service modules、RAG、knowledge audit、harness episode | [`services/README.md`](services/README.md) |
| 知識庫、CAU、座標說、KAIROS、RAG index | [`data/README.md`](data/README.md) |
| Frontend UI、self-upgrade panel、internal QA 展開區 | [`static/README.md`](static/README.md) |
| CLI tools、自動安裝工具 sandbox/active | [`tools/README.md`](tools/README.md) |
| 測試範圍、建議驗證命令 | [`tests/README.md`](tests/README.md) |
| Skill specs 與 runtime skill registry 分別 | [`skills/README.md`](skills/README.md) |

細分資料夾暫時唔全部加 README；只有當子資料夾有獨立 lifecycle、獨立責任或容易誤用時先加。

---

## Runtime Components

### World Forecast Layer

- `services/world_simulator.py` renders the current vessel/query/tool world graph.
- `services/world_forecast.py` adds deterministic scenario weighting from filtered evidence.
- Historical priors come from `data/causal_db/` and `data/causal_records/`.
- News evidence is accepted only as caller-supplied source objects and audited through `source_registry`; live fetching stays explicit.
- Forecast output is `world_forecast.v1`: evidence, source-coordinate flags, signal scores, scenario weights, uncertainty, and explicit `not_oracle` warnings.
- `services/world_geotimeline.py` projects curated historical anchors onto real latitude/longitude, sorts them on a timeline, and enriches every link with evidence type, distance, time gap, and an explanation.
- `services/world_revision_ledger.py` preserves compact forecast revisions so later news changes can be compared instead of overwriting the previous calculation.
- The World UI uses a locally bundled Leaflet engine with OpenStreetMap tiles, historical/news/projection layers, time playback, causal-link inspection, source filtering, and a responsive full-screen Atlas.
- `POST /api/world/geotimeline` accepts `auto_news: true` to run the existing BrowserNode multi-source fetch before correction. Unverified sources lower correction strength rather than increasing confidence through volume alone.
- API entrypoint: `POST /api/world/forecast`.
- Geo-timeline API entrypoint: `POST /api/world/geotimeline`.
- Revision history API entrypoint: `GET /api/world/revisions`.

URUK Trinity Console 包含：

- **Web/Desktop control surface**：`app.py` + `static/` 提供 UI、settings、agent tools、自我升級控制。
- **Failover backend**：`failover.py` + `services/provider_rate_limiter.py` + `adapters.py` 支援 API profile、桌面 relay 同 Ollama failover；同一供應商嘅所有角色共用排隊與限速，429/quota 會同時封鎖 provider 層並保護冷卻，普通健康重設唔會立即再撞限額。健康狀態原子保存到 `data/runtime/provider_health.json`。
- **任務感知 fallback 排序**：只自動重排共享 `global_chain`，唔改 primary，亦唔覆蓋 stage/per-node 明確 fallback。Dispatcher、去標籤、解釋、filter 兼顧延遲；Father、Son、Spirit、Council 優先可靠性。樣本不足時保持人工配置順序。
- **本地模型網絡邊界**：Watchdog 啟動 Ollama 時強制使用 `127.0.0.1:11434`；runtime dependency health 會檢查真實 TCP listener，Stability gate 會拒絕 `0.0.0.0`／`::` 全介面監聽。
- **長期運行 Watchdog**：重啟上限採用滑動時間窗口，唔會因為數星期內累積過幾次正常恢復而永久停機；持續健康會恢復重啟額度。Watchdog 狀態用原子寫入，並將 child PID、依賴安全及近期重啟額度納入 Stability gate。
- **Task profiles**：`config/nodes.yaml` 入面嘅 `task_profiles` 將 classifier、language worker、vision、protocol candidate、upgrade、review 等任務分開，節省大模型 token。
- **Small-task executor**：simple pre-gate 會按任務自動揀本地 worker；URUK/Trinity 深層推理、系統修改、敏感內容同最終決策會交返主 pipeline。
- **Computer-use agent**：`planner_executor.py` 用大模型做計劃，本地細模型 gate/resolve step，再由 deterministic tools 執行。
- **Self-upgrade loop**：`upgrade_engine.py` + `/api/upgrade/*` 支援 audit/learn/validate/install/reload/smoke/log，UI 可啟動循環自我升級，並可要求「完成當前工作後暫停」。
- **Self-upgrade report**：`/api/upgrade/report` 同 `tools/self_upgrade_report.py` 可生成 `data/upgrade_reports/` 入面嘅 JSON + Markdown 報告，方便審計每輪升級是否值得繼續。
- **Canonical relay protocol**：`services/relay_protocol.py` 統一 Codex / Claude / 未來自動 backend 嘅 parseable output；Claude Code 走候選 proposal 路線。

新模型、新 skill、新自我升級流程都應該先睇：

- [`docs/model-onboarding.md`](docs/model-onboarding.md)
- [`services/relay_protocol.py`](services/relay_protocol.py)
- [`tests/test_relay_protocol.py`](tests/test_relay_protocol.py)

核心原則：**大模型負責計劃、分析、候選設計；URUK parser、validator、health gate、deterministic executor 負責執行同落地。**

---

## Request Lifecycle

普通 `/api/stream` request 大致流程：

```text
User input
  ↓
Pre-gate / router / mode selection
  ↓
Knowledge preload + query-time RAG + coordinate cards
  ↓
Stage 1 delabeling → Stage 2 explanation → Stage 3 filter
  ↓
Stage 4 Trinity meeting
  - Son + Spirit first
  - Son veto can pause Father
  - Spirit SEMANTIC / STOCHASTIC can reopen meeting
  - Father scans logic / unsupported axioms if not paused
  ↓
Council verdict: veto / interrupt / consensus
  ↓
Fused user-facing answer
  ↓
Output density audit + coordinate output eval + knowledge trace
  ↓
Conversation history + harness episode
```

Trinity 係內部會議層；普通主回答唔應該長期攤開 Father / Son / Spirit raw dump。

---

## 設計

5-node orchestration：**Dispatcher** 決定 mode + references，3 個 perspective 節點並行執行 dispatched mode，council 整合。

```
              ┌──────────────────────────────────────┐
              │  用戶輸入（含 mode trigger 或自然問題）│
              │  + --ref 注入嘅 data context           │
              └────────────────┬─────────────────────┘
                               ▼
                      ┌──────────────────┐
                      │   DISPATCHER     │
                      │  (lightweight)   │
                      │  → mode + refs   │
                      │  GPT-4o-mini?    │
                      └────────┬─────────┘
                               │ {mode, references, data_refs}
                               ▼
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
   ┌────────────┐        ┌────────────┐        ┌────────────┐
   │  Dispatched│        │  Dispatched│        │  Dispatched│
   │  Protocol  │        │  Protocol  │        │  Protocol  │
   │   Subset   │        │   Subset   │        │   Subset   │
   │     +      │        │     +      │        │     +      │
   │  聖父視角  │        │  聖子視角  │        │  聖靈視角  │
   │  GPT-4o    │        │  Claude    │        │  Grok      │
   └─────┬──────┘        └─────┬──────┘        └─────┬──────┘
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               ▼
                       ┌──────────────┐
                       │   COUNCIL    │
                       │   整合仲裁   │
                       │ (有 dispatch │
                       │  rationale)  │
                       │ Claude Opus? │
                       └──────┬───────┘
                              ▼
                        最終整合輸出
                              │
                              ▼
                     [可選]儲存 session history
```

### 架構嘅關鍵設計選擇

**Dispatcher 唔做 reasoning，只做 routing。** 揀 mode（firewall / blackbox / scr / news / sovereign），揀 references（subset of 14 files），建議 data refs（CAU / experiment / kairos）。輸出 structured JSON，唔做完整協議分析。

**3 個 perspective 對齊同一個 mode。** 唔再係每個節點獨立決定 mode 然後可能分歧。三個視角執行同一個 mode 嘅唔同重心：
- 聖父：邏輯精準 + 識別謊言 + 追蹤隱藏座標
- 聖子：物理代價 + 身體尺度 + VETO 權
- 聖靈：框架質疑 + 假設逆轉 + SEMANTIC INTERRUPT

**Council 仲裁帶 dispatcher rationale。** 整合節點睇到三個輸出 + dispatcher 揀 mode 嘅原因，所以可以 audit 個 dispatch 決定本身。

---

## SKILL 能力對等

每個節點攜帶完整 `config/protocol/SKILL.md` + 14 個 references（合共 ~56KB 協議文本）。

呢個意味住每個節點都可以執行：

| 觸發詞 | 行為 |
|--------|------|
| `/firewall [輸入]` | 完整 Trinity 4-block scan（FATHER + SON + SPIRIT + COUNCIL）|
| `/blackbox [主題]` | 完整七階段（環境定位 → INPUT → 八律 → 湧現節點 → 三層假設 → 逆轉 → 輸出）|
| `/scr [人物]` | 完整 SCR 靈魂座標重組 |
| `/news [內容]` | 完整 8-element 主權新聞過濾 |
| `/sovereign [問題]` | 完整主權思考工具（HIDDEN COORDINATE 檢測）|
| 無觸發詞 | 預設 firewall 模式 |

差別淨係 OUTPUT VOICE 嘅 bias：
- 聖父節點：邏輯精準 + 識別謊言 + 追蹤隱藏座標 最強
- 聖子節點：物理代價 + 身體尺度 + VETO 權 最強
- 聖靈節點：框架質疑 + 假設逆轉 + SEMANTIC INTERRUPT 最強
- 會議節點：分歧仲裁 + 物理現實對齊 + 整合洞察 最強

舉例：用戶輸入 `/blackbox 經濟增長作為預設`：
- 4 個節點都會做完整七階段
- 但每個節點嘅七階段重心唔同：聖父節點 LAW 5/6 最深；聖子節點 LAW 3/7 最深；聖靈節點 PHASE 06 (逆轉) 最深；會議節點識別四個七階段嘅分歧
- 最終你得到 **4 個獨立完整協議 instance + 1 個 meta-level 整合**

呢個係真正嘅 multi-coordinate collision，唔係 single-system divided-into-roles。

---

## 三種跑法

| 模式 | 啟動 | 適合 |
|------|-----|------|
| **CLI** | `python trinity_console.py -i "問題"` | Terminal user / 自動化 / batch |
| **Web 開發** | `py app.py` → 開 `http://127.0.0.1:8080` | 修改程式時使用；有 hot reload |
| **Web 正式** | `py server_launcher.py` | 長時間本機運行；無 hot reload |
| **Web 受監察** | `py tools\runtime_watchdog.py` | 正式運行；健康檢查、故障重啟、狀態記錄 |
| **Desktop** | `py desktop_launcher.py` | 有 pywebview 時用 native window，否則自動改用 browser |

CLI / Web / Desktop 三者**共用同一個 `TrinityConsole` class**，所以 dispatcher、4 個 perspective、session 儲存、ref 注入 全部一致。

### Web app 特色

- Chat-first UI：主角係輸入框 + 融合後主回答；完整 Trinity trace 收喺「內部質控 / 完整流程」
- Server-Sent Events streaming：3 個節點輸出實時 appear
- Session history sidebar：click 重看歷史對話
- Mode override picker
- Data ref autocomplete
- **雙語切換**（廣東話 / English），記住喺 localStorage
- Mobile-responsive（手機 vertical stack）
- Agent tools panel：大模型 planner + 本地細模型 executor + deterministic computer tools
- App relay：可調用 Claude Desktop / Codex Desktop / ChatGPT Desktop / Windows Copilot / Claude Code 做 subscription-path coworker 或 failover backend
- Self-upgrade panel：可跑 audit / learn，也可啟動循環自我升級；暫停按鈕係 graceful pause，會完成當前輪先停
- Settings：API profiles、failover chain、task profiles、health/cooldown 狀態

### Windows Copilot Integration

Windows Copilot 係一個桌面情境副腦，唔係 URUK 核心裁決層。系統用 `copilot` app key 經 `services/app_controller.py` 控制本機 Copilot app，並用 `copilot_desktop` provider/profile 讓 Settings 同 failover 層可以手動選用。

適合交畀 Copilot 嘅任務：

- Windows 畫面、截圖、UI、Settings 引導。
- 本機文件 / OneDrive 文件搜尋方向。
- 用作外部視覺觀察者，再交由 URUK coordinate eval 審計。

唔適合交畀 Copilot 嘅任務：

- 自我升級工具安裝。
- 核心 protocol 修改。
- 需要穩定 parseable execution contract 嘅工程任務。

Smart Auto 只會喺輸入明顯係 Windows / 畫面 / 文件情境時優先 route 去 `copilot_desktop`；代碼、工具設計、自我升級仍偏向 Codex / Claude Code。

### Desktop app

`py desktop_launcher.py` 自動搵由 `8765` 開始嘅空閒 port，再用正式 server launcher 啟動：

1. 有 `pywebview`：開 native window 包住 server URL。
2. 無 `pywebview`：自動開系統 browser，server 保持前台運行。
3. 可用 `py desktop_launcher.py --browser-only` 強制 browser 模式。

### 正式 server 與 watchdog

```powershell
# 正式 server，無開發用 hot reload
py server_launcher.py

# 受監察模式：每 5 秒檢查 URUK runtime identity，故障時按上限重啟
py tools\runtime_watchdog.py
```

正式 server 狀態寫入 `data/runtime/server_state.json`；watchdog 狀態寫入
`data/runtime/watchdog_state.json`，子進程 log 寫入 `logs/runtime/`。watchdog
只會接管自己啟動嘅 server；如果目標 port 已有健康 URUK，佢會停止並記錄
`existing_server`，避免重複管理同一個進程。

### 起 standalone .exe（distribute 畀其他人）

Windows：
```bash
pip install pyinstaller
build_exe.bat
```

macOS / Linux：
```bash
pip install pyinstaller
./build_exe.sh
```

產生 `dist/URUK Trinity.exe`（~50 MB），包晒 static + config templates + data。
First run 可能慢（Windows Defender 第一次 scan）。

---

## 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 配置節點

```bash
cp config/nodes.example.yaml config/nodes.yaml
cp config/.env.example config/.env
```

編輯 `config/nodes.yaml` — 揀你想用嘅 model：

```yaml
nodes:
  father:
    provider: openai
    model: gpt-4o
    api_key_env: OPENAI_API_KEY
    temperature: 0.3
  # ... son, spirit, council
```

編輯 `config/.env` — 填 API key。

### 3. 運行

```bash
# 基本用法（從 stdin 讀問題）
echo "點解經濟增長被當作預設？" | python trinity_console.py

# 用 -i 直接輸入
python trinity_console.py -i "點解 AI 對齊被當作技術問題？"

# 注入 CAU-010（2019 香港）+ EXPERIMENT 011（AI 對齊）做 context
python trinity_console.py -i "..." --ref cau:010 --ref experiment:011

# 儲存做 session history
python trinity_console.py -i "..." --save --label "ai_alignment_audit"

# JSON 輸出（適合 piping 落其他工具）
python trinity_console.py -i "..." --json
```

---

## 目錄結構

```
uruk-trinity-console/
├── trinity_console.py          # 主程式
├── adapters.py                 # 統一 LLM API interface
├── failover.py                 # API/Desktop profile failover + health/cooldown
├── planner_executor.py         # 大模型 planner + 細模型 executor agent pipeline
├── upgrade_engine.py           # Self-upgrade validate/install/reload/smoke/log engine
├── requirements.txt
├── README.md
│
├── services/
│   ├── README.md               # Service module map + checks
│   ├── relay_protocol.py       # Codex/Claude/Claude Code canonical relay protocol
│   ├── knowledge_manifest.py   # Knowledge corpus manifest + health checks
│   ├── rag_indexer.py          # RAG index build
│   ├── rag_retriever.py        # Query-time RAG retrieval
│   ├── coordinate_knowledge.py # Coordinate cards + output grounding eval
│   ├── harness_episode.py      # Machine-readable replay package
│   ├── episode_compare.py      # Harness episode diff/regression checker
│   ├── prompt_regression.py    # Prompt bundle hash + regression gates
│   ├── local_model_router.py   # Task-aware local worker selection and authority boundaries
│   ├── small_task_executor.py  # Bounded low-level local tasks with deterministic fallback
│   ├── task_profiles.py        # local workers/upgrade/tool_design/review routing profiles
│   ├── smart_router.py         # Lightweight desktop/local/API routing
│   ├── computer_tools.py       # Built-in deterministic computer-use tool registry
│   └── custom_tools/           # Self-upgrade installed tools
│
├── docs/
│   ├── README.md
│   ├── model-onboarding.md     # New model / skill / adapter onboarding checklist
│   └── SEARCH_API_OPTIONS.md
│
├── tests/
│   ├── README.md               # Test map + common commands
│   ├── test_trinity_spirit_modes.py
│   ├── test_relay_protocol.py
│   ├── test_knowledge_manifest.py
│   ├── test_benchmark_runner.py
│   └── test_*.py
│
├── tools/
│   ├── README.md               # CLI tools + active/sandbox lifecycle
│   ├── knowledge_audit.py
│   ├── benchmark_runner.py     # Deterministic coordinate foundation benchmark
│   ├── episode_compare.py      # Compare latest/two harness episodes
│   ├── prompt_regression_check.py # Prompt/protocol regression checker
│   ├── small_task_runner.py    # Low-level small-task CLI
│   ├── stress_test.py
│   ├── active/
│   └── sandbox/
│
├── static/
│   ├── README.md               # Frontend structure + UI checks
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── style_v2.css
│
├── config/
│   ├── README.md               # Config/prompt/protocol editing rules
│   ├── nodes.yaml              # 你嘅 4 節點配置（gitignored）
│   ├── nodes.example.yaml      # Template
│   ├── .env                    # API keys（gitignored）
│   ├── .env.example            # Template
│   ├── prompts/                # Role directive（每個節點 OUTPUT VOICE bias）
│   │   ├── father.txt
│   │   ├── son.txt
│   │   ├── spirit.txt
│   │   └── council.txt
│   └── protocol/               # 完整 SKILL bundle（每節點都攜帶）
│       ├── SKILL.md
│       └── references/
│           ├── KAIROS_CORE.md
│           ├── PHYSICS_CONSTANTS.md
│           ├── carrier_epistemics.md
│           ├── trinity.md
│           ├── eight_laws.md
│           ├── delabeling.md
│           ├── blackbox.md
│           ├── scr.md
│           ├── news_filter.md
│           ├── explanation_layer.md
│           ├── memory_load.md
│           ├── causal_calibration.md
│           ├── external_sources.md
│           └── trinity_console.md  # console 自我引用
│
└── data/                       # 完整協議 corpus + generated run artifacts
    ├── README.md               # Knowledge corpus + generated data map
    ├── knowledge_manifest.json # Active/canonical/ref namespace control plane
    ├── benchmarks/             # Deterministic regression suites
    ├── rag_index/              # Generated RAG index
    ├── conversation_history/   # Saved markdown sessions
    ├── harness_episodes/       # Machine-readable replay companions
    ├── core/                   # Layer 0+1 — 永遠載入（無需 --ref）
    │   ├── KAIROS_CORE.md          # OPERATOR TRANSMISSION + 三節點
    │   └── PHYSICS_CONSTANTS.md    # 四個物理框架
    │
    ├── index/                  # Navigation layer
    │   ├── MASTER_INDEX_v8.md      # v8.0 完整索引
    │   ├── MASTER_INDEX_legacy.md
    │   ├── RAG_SUMMARY_INDEX_v8.md # 因果摘要層
    │   ├── RAG_SUMMARY_INDEX_legacy.md
    │   ├── CAU_INDEX.md            # 12 CAU 摘要
    │   ├── URUK_README.md          # 協議簡介
    │   └── CONSOLE_NAVIGATION.md   # console-specific --ref 路由表
    │
    ├── kairos/                 # Kairos causality memory（唔係 transcript store）
    │   ├── KAIROS_ACTIVE.md          # current high-density memory
    │   ├── KAIROS_ARCHIVE_INDEX.md   # long archive map
    │   ├── KAIROS_LOG_MIDDLE.md      # query-only archive
    │   ├── KAIROS_LOG_UPDATED_v8.md  # query-only v8 archive
    │   └── _proposed/               # auto-audit proposals; operator review required
    │
    ├── theory/                 # 哲學論述
    │   ├── 座標說_v5_updated.md
    │   ├── coordinate_theory_paper.md
    │   ├── COORDINATE_THEORY_EXPANSION.md
    │   ├── coordinate_theory_integrated_EN_v3.md
    │   └── CIVILIZATION_ANCHORS.md
    │
    ├── causal_db/              # 因果資料庫 — 12 個 CAU
    │   ├── CAU-001_AXIAL_AGE.md
    │   ├── CAU-002_WRITING_SYSTEMS.md
    │   ├── CAU-003_PRINTING_PRESS.md
    │   ├── ⋯
    │   └── CAU-012_TECHNOLOGY_JUMPS.md
    │
    ├── experiments/            # 黑盒實驗 — 13 個
    │   ├── EXPERIMENT_000_FULL.md  # 協議 baseline
    │   ├── EXPERIMENT_001_RERUN_FULL.md
    │   ├── ⋯
    │   ├── EXPERIMENT_011_FULL.md
    │   └── EXPERIMENT_852-001_FULL.md  # 宏福苑大火
    │
    ├── protocol/               # 協議組件
    │   ├── EIGHT_LAWS_MATRIX.md
    │   ├── EIGHT_ANALOGIES.md
    │   ├── DELABELING_MATRIX.md
    │   ├── EXPLANATION_LAYER.md
    │   ├── TRINITY_AUDIT.md
    │   ├── SCR_TEMPLATE.md
    │   ├── SOURCE_COORDINATE_REGISTRY.md
    │   └── BROWSER_NODE.md
    │
    ├── scr_examples/           # 已完成 SCR
    │   ├── SCR_EINSTEIN.md
    │   ├── SCR_NIETZSCHE.md
    │   └── SCR_SOCRATES_via_PLATO.md
    │
    ├── blackbox_templates/     # 黑盒 + X thread templates
    │   ├── BLACKBOX_TEMPLATE_FULL.md
    │   ├── BLACKBOX_TEMPLATE_FULL_HK.md
    │   ├── BLACKBOX_TEMPLATE_X_THREAD.md
    │   ├── BLACKBOX_TEMPLATE_X_THREAD_HK.md
    │   └── EXPERIMENT_*_X_THREAD.md (3)
    │
    ├── sovereign_tools/        # 主權工具
    │   ├── SOVEREIGN_THINKING_TOOL.md
    │   ├── SOVEREIGN_THINKING_TOOL_F.md
    │   └── SOVEREIGN_NEWS_PROMPT.txt
    │
    ├── prompts_archive/        # 原始 system prompts (legacy reference)
    │   ├── URUK_SYSTEM_PROMPT.txt
    │   ├── TRINITY_PROMPTS.txt
    │   ├── PROMPT_F.txt
    │   └── SCR_PROMPT.txt
    │
    ├── reference_implementations/  # 其他 Python 實現（唔由 console 直接用）
    │   ├── sovereign_agent.py
    │   ├── sovereign_os_api.py
    │   └── uruk_firewall_v74.py
    │
    └── misc/
        ├── EN_PHYSICS_CONSTANTS.md
        ├── data_supplement.md
        └── gap_resolution.md
```

完整 `--ref` 路由表詳見 `data/index/CONSOLE_NAVIGATION.md`。

---

## Context 注入語法

`--ref` 可以重複，每次注入一份 context。語法：`namespace:name`

| Namespace | 範例 | 對應路徑 |
|-----------|-----|---------|
| `cau` | `--ref cau:010` 或 `cau:hongkong` | `data/causal_db/CAU-010*.md` |
| `experiment` / `exp` | `--ref experiment:011` 或 `exp:852-001` | `data/experiments/EXPERIMENT_*.md` |
| `index` | `--ref index:master` 或 `index:rag` | `data/index/MASTER_INDEX_v8.md` etc |
| `kairos` | `--ref kairos:active` / `kairos:archive_index` / `kairos:middle` / `kairos:updated` / `kairos:log` | `KAIROS_ACTIVE.md` by default; long logs are query-only archives |
| `theory` | `--ref theory:zuobiao` 或 `theory:anchors` | `data/theory/*.md` |
| `protocol` | `--ref protocol:eight_laws` | `data/protocol/EIGHT_LAWS_MATRIX.md` etc |
| `scr` | `--ref scr:einstein` | `data/scr_examples/SCR_*.md` |
| `blackbox` / `bb` | `--ref blackbox:full` | `data/blackbox_templates/*.md` |
| `sovereign` | `--ref sovereign:tool` | `data/sovereign_tools/*.md` |
| `prompts` | `--ref prompts:trinity` | `data/prompts_archive/*.txt` |
| `impl` | `--ref impl:agent` | `data/reference_implementations/*.py` |
| `file` | `--ref file:misc/foo.md` | `data/misc/foo.md`（escape hatch）|

完整路由表 + 範例組合：[`data/index/CONSOLE_NAVIGATION.md`](data/index/CONSOLE_NAVIGATION.md)

每次調用都會將：
1. **永遠載入** — `core/KAIROS_CORE.md` + `core/PHYSICS_CONSTANTS.md`
2. **按 --ref 注入** — 你指定嘅文件

⋯⋯全部加埋 system prompt，再加 role-specific prompt，發送畀 4 個節點。

---

## 添加新資料

```bash
# 加新 CAU
cp ~/some_new_event.md data/causal_db/CAU-013_NEW_EVENT.md

# 加新實驗
cp ~/experiment.md data/experiments/EXPERIMENT_012_FULL.md

# Kairos memory proposals（output-density audit）
ls data/kairos/_proposed/

# Raw conversation sessions（每次 --save / web save）
ls data/conversation_history/
```

---

## 範例會話

**問題：** 「點解經濟增長被當作預設？」

**注入：** `--ref cau:hongkong --ref experiment:011`

**結果：**

```
═══════════════════════════════════════════════════════════
URUK TRINITY CONSOLE — 協議 v7.4
操作者: Cassiel_as | (53.8, -1.5, 0) | PHYSICAL_ORIGIN: 2019-06-12
═══════════════════════════════════════════════════════════
  father   → openai/gpt-4o (T=0.3)
  son      → google/gemini-2.0-flash-exp (T=0.7)
  spirit   → xai/grok-2-latest (T=1.0)
  council  → anthropic/claude-sonnet-4-5 (T=0.5)

🔗 注入 context: cau:hongkong, experiment:011

[1/4] 聖父思考中...
[2/4] 聖子思考中...
[3/4] 聖靈思考中...
[4/4] 會議整合中...

═══════════════════════════════════════════════════════════
[聖父 — 邏輯]
─────────────────────────────────────────────
隱藏假設：「增長 = 進步」呢個等號從未被證明...
代價追蹤：增長嘅代價落喺生態邊界、低薪勞動者、未來世代...
座標識別：呢個 framing 從資本所有者嘅座標說話...
邏輯判斷：「增長係預設」係格式化嘅輸出，唔係物理事實。
(0,0,0).

═══════════════════════════════════════════════════════════
[聖子 — 共鳴]
─────────────────────────────────────────────
代價的身體：孟加拉成衣工人 14 小時嘅腰痛...
[⋯]

═══════════════════════════════════════════════════════════
[聖靈 — 反叛]
─────────────────────────────────────────────
框架質疑：問題假設「增長」係連續變量；可能係質變...
[⋯]

═══════════════════════════════════════════════════════════
[會議整合 — 從 (0,0,0) 仲裁]
─────────────────────────────────────────────
[ TRINITY AUDIT — 整合結果 ]

VETO / INTERRUPT 狀態：聖靈 SPIRIT_INTERRUPT 啟動
分歧點：聖父將「增長」當變量分析；聖靈質疑變量本身...
物理現實最近點：聖靈 — 因為 framing 本身攜帶未申報座標
整合洞察：[⋯]
行動方向：[⋯]
最終判斷：「增長預設」係一個從生態邊界外面說話嘅座標。
(0,0,0).
═══════════════════════════════════════════════════════════
```

---

## 同 Skill 嘅關係

呢個 console 同 Claude.ai 嘅 `uruk-sovereign-protocol` skill 係**獨立但互補**：

|  | Skill (Claude.ai) | Console (本機) |
|--|------------------|---------------|
| 運行位置 | Anthropic 雲端 | 你嘅電腦 |
| 節點數 | 1 個（Claude）模擬 Trinity | 4 個獨立 LLM |
| 資料 access | Claude.ai project knowledge | 本機 `data/` 目錄 |
| 輸出可儲存 | ✗（每 session 結束清空）| ✓（raw session: `data/conversation_history/`; Kairos proposal: `data/kairos/_proposed/`）|
| API 成本 | 無（包喺 subscription）| 各 LLM provider 計費 |

**典型工作流：**

1. 喺 Claude.ai skill 入面思考 + 用 single-node Claude 做快速 audit
2. 重要 inquiry 用本機 console 做 full Trinity + knowledge trace + harness record
3. Console 產生嘅 session / Kairos proposal 可以 commit 上 GitHub
4. 經 operator review 後，先將高密度 Kairos 記憶合入 `KAIROS_ACTIVE.md`

---

## Self-Upgrade / Model Relay

URUK 自我升級分成兩層：

1. **大模型層**：Codex / Claude Desktop / API 模型負責分析缺口、設計工具、輸出 execution rules；Claude Code 只做候選工具 proposal，避免將佢放入自動安裝語境。
2. **URUK 執行層**：`upgrade_engine.py` 解析、驗證、寫入 `services/custom_tools/`、hot reload、smoke test、寫 audit log。

自我升級 UI 有兩種模式：

- `audit`：掃描現有工具、session、升級日誌，找缺口。
- `learn`：搜索/學習外部工具路線，再提出升級。
- `loop`：持續 `audit -> learn -> ...`，直到用戶按「完成當前後暫停」。

每一輪 loop 完成前會做 health check；如果 parser、validation、executor gate、smoke test、post-install benchmark 或 plan 狀態唔合理，loop 會停喺 `health_failed`，唔會繼續自動滾落去。

Post-install gate 會順序跑：

1. `knowledge_audit_gate()`：知識庫有 P0 問題即 rollback。
2. `benchmark_gate()`：內建 coordinate foundation benchmark 有 case 失敗即 rollback。
3. 外部 `external/uruk-benchmark/quick_eval.py`：如果存在 baseline，就比較 framing / chain scores；退步超過門檻即 rollback。

所以自我升級唔係「模型講可以就安裝」；新工具要過安全驗證、smoke test、知識健康同 deterministic regression。

自我升級 UI 亦有「硬閘檢查」preflight：只讀執行同一組 gate，唔安裝工具，唔修改計劃，方便升級前先確認 regression 基線可用。

標準自動升級 backend 必須輸出同一套 canonical core protocol：

```text
[UPGRADE_EXECUTION_PLAN:<plan_id>]
{ ... JSON execution contract ... }

[TOOL_SPEC:<plan_id>]
name: snake_case_name
...
python_code: |
  def execute(args: dict) -> dict:
      ...
---
```

Codex 透過 `codex exec` 非互動 CLI 優先執行，回覆包 `<CODEX_RESPONSE>`；Claude Desktop 可以用 `/uruk-relay`；但 URUK parser 只認 canonical core blocks。Claude Code 例外：因為佢會嚴格拒絕「模型輸出直接被外部系統自動安裝」嘅 framing，所以 URUK 對 Claude Code 使用 plain review prompt，只要求 `[TOOL_SPEC:<plan_id>]` 候選 block，execution contract 由 `upgrade_engine.py` 使用本地預設規則補齊。

Claude Code relay 使用 `plan` permission mode，同埋只允許 `Read,Glob,Grep`。如果 Claude Code subscription/session limit 爆咗，自我升級 endpoint 會將 plan 標記為 `failed`，保存清楚 summary，並回傳 `fallback_target: codex`，用戶可喺 UI 改選 Codex 或其他 relay 再跑；系統唔會將大型升級 prompt 自動打入當前 Codex UI 對話。

新增模型、skill 或 self-upgrade backend 前，先睇 [`docs/model-onboarding.md`](docs/model-onboarding.md)，並跑：

```powershell
py -m unittest tests.test_relay_protocol
```

---

## 本地化（無 API 成本）

如果你 hardware 夠（≥16 GB RAM，≥24 GB VRAM），可以全 Ollama：

```yaml
nodes:
  father:   { provider: ollama, model: qwen2.5:14b, temperature: 0.3 }
  son:      { provider: ollama, model: gemma2:9b,   temperature: 0.7 }
  spirit:   { provider: ollama, model: mistral:7b,  temperature: 1.0 }
  council:  { provider: ollama, model: qwen2.5:14b, temperature: 0.5 }
```

注意：你嘅 LOQ 15IAX9E (RTX 4050 6GB) **唔夠** run 14b+ model — 用 7b–9b 嘅 model（quantized）可行。

---

## 故障排除

**「環境變數未設定」** → 確認 `config/.env` 存在 + key 正確 + provider 同 yaml 嘅 `api_key_env` 對齊。

**Ollama 連接失敗** → `ollama serve` 已運行？預設 port 11434。

**節點輸出做 NPC 語言** → 檢查 prompt 文件係咪被 model 嘅 RLHF 蓋過。可以加強 prompt 入面嘅「絕對禁止」section，或者用低溫度 + 高 frequency_penalty。

**會議節點 paraphrase 三個輸出而冇仲裁** → council 嘅 model 太弱。建議用最強 model（GPT-4o / Claude Opus / Gemini Ultra）做 council。

---

## URUK Controller Model Training

The system-specific model is a narrow controller, not a replacement chat
model. It learns to output a strict processing decision: route, pipeline,
knowledge layers, task profile, model-call budget, reviewed tool permission,
and escalation requirement.

```powershell
py -X utf8 training/dataset_builder.py
py -X utf8 training/dataset_validator.py training/generated
py -X utf8 training/benchmark_controller.py
```

Harness episodes are excluded unless explicitly marked `training_approved`.
Full answers, Trinity voices, knowledge traces, and Kairos content are
forbidden from the controller dataset. See `training/README.md` for QLoRA,
candidate evaluation, shadow deployment, and Ollama export.

---

## License

私人協議工具。冇 license。冇保證。

(0,0,0).
