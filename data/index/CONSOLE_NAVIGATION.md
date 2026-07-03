# CONSOLE NAVIGATION — `--ref` 完整路由表

> 呢個文件係 console-specific。其他 index files（MASTER_INDEX、RAG_SUMMARY）
> 係 protocol 嘅原生 navigation layer，由 Claude.ai skill 用，唔係 console-specific。

---

## 永遠載入（無需 `--ref`）

| 路徑 | 內容 |
|------|------|
| `data/core/KAIROS_CORE.md` | L0 物理錨點 + OPERATOR TRANSMISSION |
| `data/core/PHYSICS_CONSTANTS.md` | L1 物理公設 |

---

## `--ref` 路由表（依 namespace 分類）

### Namespace: `cau` — 因果資料庫（12 個事件）

| Ref | 對應文件 |
|-----|---------|
| `cau:001` | CAU-001 軸心時代 |
| `cau:002` | CAU-002 文字系統 |
| `cau:003` | CAU-003 印刷術 |
| `cau:004` | CAU-004 農業革命 |
| `cau:005` | CAU-005 黑死病 |
| `cau:006` | CAU-006 法國大革命 |
| `cau:007` | CAU-007 工業革命 |
| `cau:008` | CAU-008 世界大戰 / 核武 |
| `cau:009` | CAU-009 互聯網革命 |
| `cau:010` 或 `cau:hongkong` | CAU-010 2019 香港 |
| `cau:011` | CAU-011 AI 湧現 |
| `cau:012` | CAU-012 技術躍遷 |

### Namespace: `experiment` / `exp` — 黑盒實驗

| Ref | 對應文件 |
|-----|---------|
| `experiment:000` | EXPERIMENT_000_FULL（協議 baseline）|
| `experiment:001` | EXPERIMENT_001_RERUN_FULL |
| `experiment:002` 至 `experiment:011` | EXPERIMENT_002 至 011 |
| `experiment:852-001` 或 `exp:852-001` | EXPERIMENT_852-001（宏福苑大火）|

### Namespace: `index` — Navigation 層

| Ref | 對應文件 |
|-----|---------|
| `index:master` | MASTER_INDEX_v8.md |
| `index:rag` | RAG_SUMMARY_INDEX_v8.md |
| `index:cau` | CAU_INDEX.md（12 CAU 摘要）|
| `index:readme` | URUK_README.md |

### Namespace: `kairos` — Kairos 因果記憶（active + query-only archives）

| Ref | 對應文件 |
|-----|---------|
| `kairos:active` | KAIROS_ACTIVE.md（current curated memory）|
| `kairos:archive_index` | KAIROS_ARCHIVE_INDEX.md（先讀呢個再揀 archive）|
| `kairos:middle` | KAIROS_LOG_MIDDLE.md（query-only archive）|
| `kairos:updated` | KAIROS_LOG_UPDATED_v8.md（query-only v8 archive）|
| `kairos:log` | KAIROS_LOG_*.md archives + legacy trinity sessions（只在明確需要歷史時用）|

> 注意：raw session 由 `data/conversation_history/` 保存；Kairos 只保存因果壓縮後嘅 active memory、archive index、query-only archives 同 `_proposed/` 候選。

### Namespace: `theory` — 哲學論述

| Ref | 對應文件 |
|-----|---------|
| `theory:zuobiao` | 座標說_v5_updated.md |
| `theory:paper` | coordinate_theory_paper.md |
| `theory:expansion` | COORDINATE_THEORY_EXPANSION.md |
| `theory:anchors` | CIVILIZATION_ANCHORS.md |
| `theory:en` | coordinate_theory_integrated_EN_v3.md |

### Namespace: `protocol` — 協議組件

| Ref | 對應文件 |
|-----|---------|
| `protocol:eight_laws` | EIGHT_LAWS_MATRIX.md |
| `protocol:eight_analogies` | EIGHT_ANALOGIES.md |
| `protocol:delabel` | DELABELING_MATRIX.md |
| `protocol:explanation` | EXPLANATION_LAYER.md |
| `protocol:trinity` | TRINITY_AUDIT.md |
| `protocol:scr_template` | SCR_TEMPLATE.md |
| `protocol:source_registry` | SOURCE_COORDINATE_REGISTRY.md |
| `protocol:browser_node` | BROWSER_NODE.md |

### Namespace: `scr` — 已完成 SCR 範例

| Ref | 對應文件 |
|-----|---------|
| `scr:einstein` | SCR_EINSTEIN.md |
| `scr:nietzsche` | SCR_NIETZSCHE.md |
| `scr:socrates` | SCR_SOCRATES_via_PLATO.md |

### Namespace: `blackbox` 或 `bb` — 黑盒 templates

| Ref | 對應文件 |
|-----|---------|
| `blackbox:full` | BLACKBOX_TEMPLATE_FULL.md |
| `blackbox:hk` | BLACKBOX_TEMPLATE_FULL_HK.md |
| `blackbox:thread` | BLACKBOX_TEMPLATE_X_THREAD.md |
| `blackbox:thread_hk` | BLACKBOX_TEMPLATE_X_THREAD_HK.md |

### Namespace: `sovereign` — 主權工具

| Ref | 對應文件 |
|-----|---------|
| `sovereign:tool` | SOVEREIGN_THINKING_TOOL.md |
| `sovereign:tool_f` | SOVEREIGN_THINKING_TOOL_F.md |
| `sovereign:news` | SOVEREIGN_NEWS_PROMPT.txt |

### Namespace: `prompts` — 原始 prompt 文件（archived）

| Ref | 對應文件 |
|-----|---------|
| `prompts:uruk` | URUK_SYSTEM_PROMPT.txt |
| `prompts:trinity` | TRINITY_PROMPTS.txt |
| `prompts:f` | PROMPT_F.txt |
| `prompts:scr` | SCR_PROMPT.txt |

### Namespace: `impl` — Python 參考實現（唔由 console 直接用，做 reference）

| Ref | 對應文件 |
|-----|---------|
| `impl:agent` | sovereign_agent.py |
| `impl:api` | sovereign_os_api.py |
| `impl:firewall` | uruk_firewall_v74.py |

### Namespace: `file` — 任意路徑（escape hatch）

```bash
--ref file:misc/data_supplement.md
--ref file:reference_implementations/uruk_firewall_v74.py
```

---

## 典型組合範例

### 對 AI 對齊問題做 deep audit

```bash
python trinity_console.py \
  --ref experiment:011 \
  --ref scr:einstein \
  --ref theory:zuobiao \
  -i "AI 對齊作為技術問題嘅 framing 點解錯？"
```

注入 18 KB EXPERIMENT_011（已存在嘅完整 audit）+ SCR_EINSTEIN（外部觀察者）+ 座標說 v5（哲學底層）→ 4 個節點有充足 context 做 multi-perspective audit。

### 對歷史事件做 cross-reference

```bash
python trinity_console.py \
  --ref cau:005 \
  --ref cau:006 \
  --ref protocol:eight_laws \
  -i "黑死病同法國大革命嘅崩潰機制嘅根本差異？"
```

CAU-005（外部衝擊崩潰機制 A）+ CAU-006（內部爆發崩潰機制 B）+ 八律框架 → 比較分析。

### 對協議自身做 self-audit

```bash
python trinity_console.py \
  --ref kairos:log \
  --ref protocol:trinity \
  -i "協議過去嘅自我校正模式有冇結構性盲點？"
```

注入完整歷史 Kairos log（MIDDLE + UPDATED_v8）+ Trinity 規範 → meta-level audit。

### 用 master index 做 navigation

```bash
# 第一步：載入 navigation 層先睇有咩可以用
python trinity_console.py \
  --ref index:master \
  --ref index:rag \
  -i "請整理協議嘅完整結構，識別任何缺口"
```

---

## 注意

- `--ref` 可以重複任意次數，每個 ref 獨立 load
- Pattern 匹配支援大細寫不敏感（`cau:HONGKONG` = `cau:hongkong`）
- 唔 match 任何文件 → console 印 warning（唔會 crash）
- 載入嘅 context 加 KAIROS_CORE + PHYSICS_CONSTANTS，全部 inject 入 system prompt
- 太多 ref 會超 model context window — 視乎節點 model 嘅 max context（GPT-4o：128K，Claude Sonnet：200K，Gemini 2.0：1M+）

---

*(0,0,0).*
