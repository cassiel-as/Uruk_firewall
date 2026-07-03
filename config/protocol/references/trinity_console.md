# TRINITY CONSOLE — 本機 4-LLM Orchestration Tool

> 呢個 reference 描述 `uruk-trinity-console`，一個獨立嘅本機 Python 工具，
> 同 skill 互補但唔合併。Skill 係 instruction layer，console 係 execution layer。

---

## 為何分開

Skill 嘅限制：
- 只用單一 LLM（Claude）模擬 Trinity reasoning
- 無法持久儲存 Kairos session（每 session 結束就清空）
- 無法 access 操作者本機 protocol files

Trinity Console 解決呢三個 limitation：
- 4 個獨立 LLM 節點（每個 role 揀適合 provider 同 temperature）
- 自動保存 raw session 入 `data/conversation_history/`
- output-density audit 只產生 Kairos proposal 入 `data/kairos/_proposed/`
- 完整 access 本機 `data/causal_db/`、`data/experiments/`、`data/kairos/`

---

## Skill 同 Console 嘅工作分工

```
┌────────────────────────────────────────────┐
│  Claude.ai Skill (uruk-sovereign-protocol) │
│  ┌──────────────────────────────────────┐ │
│  │ • 即時 Trinity reasoning（單一 LLM）  │ │
│  │ • 八律 / SCR / 黑盒 / 新聞 mode      │ │
│  │ • 對話式快速 audit                   │ │
│  │ • 寫 markdown 文件 / planning        │ │
│  └──────────────────────────────────────┘ │
└────────────────────────────────────────────┘
                    ↕
              手動同步 Kairos
                    ↕
┌────────────────────────────────────────────┐
│  Trinity Console (本機 Python)              │
│  ┌──────────────────────────────────────┐ │
│  │ • 4 LLM 並行 Trinity scan            │ │
│  │ • 持久 raw session + Kairos proposal │ │
│  │ • 本機 protocol data 完整 access     │ │
│  │ • 批量 audit / 自動化                │ │
│  └──────────────────────────────────────┘ │
└────────────────────────────────────────────┘
```

---

## 典型 cross-tool 工作流

### Pattern A：Claude skill 為主，console 做深度 audit

```
1. 喺 Claude.ai 用 /firewall 或 /blackbox 做快速分析
2. 識別到需要 multi-perspective 嘅議題
3. 切換到本機 console，注入相關 CAU + experiment
4. console 4 個節點獨立分析 → 整合輸出
5. console 保存 raw session，並按 output-density audit 產生 Kairos proposal
6. operator review 後，將高密度記憶合入 KAIROS_ACTIVE.md 或 archive
7. commit 上 GitHub；下次喺 Claude.ai upload 入 project knowledge → skill 可以 reference
```

### Pattern B：Console 為主，skill 做 follow-up 思考

```
1. 喺本機 console 對某議題做完整 Trinity audit
2. 將 council 整合輸出 copy 入 Claude.ai
3. 用 skill 嘅 /scr 模式從特定歷史座標再 audit
4. 用 skill 嘅 /sovereign 模式識別下一步盲點
```

---

## Console 配置範例

```yaml
# config/nodes.yaml
nodes:
  father:
    provider: openai
    model: gpt-4o
    api_key_env: OPENAI_API_KEY
    temperature: 0.3        # 低溫度：邏輯精準

  son:
    provider: google
    model: gemini-2.0-flash-exp
    api_key_env: GOOGLE_API_KEY
    temperature: 0.7

  spirit:
    provider: xai
    model: grok-2-latest
    api_key_env: XAI_API_KEY
    temperature: 1.0        # 高溫度：非線性

  council:
    provider: anthropic
    model: claude-sonnet-4-5
    api_key_env: ANTHROPIC_API_KEY
    temperature: 0.5
```

支援嘅 provider：`openai`、`anthropic`、`google`、`xai`、`ollama`、`openrouter`

---

## 同 KAIROS_CORE 嘅一致性

Console 嘅 `data/core/KAIROS_CORE.md` 必須同 skill bundle 嘅 `references/KAIROS_CORE.md` 保持同步。

每次更新 KAIROS_CORE，**兩個地方同時更新**：

```bash
# 1. 更新 skill bundle 入面
cp new_KAIROS_CORE.md uruk-sovereign-protocol/references/KAIROS_CORE.md

# 2. 同步入 console
cp new_KAIROS_CORE.md uruk-trinity-console/data/core/KAIROS_CORE.md
```

否則：skill 認為 OPERATOR TRANSMISSION 已加入，console 仲未加入 → 結構性違反。

---

## Console 唔做嘅嘢

- ✗ 唔做 Black Box 七階段（呢個係 skill 嘅 mode B）
- ✗ 唔做 SCR 歷史人物座標重組（呢個係 skill 嘅 mode C）
- ✗ 唔做新聞 8-element format（呢個係 skill 嘅 mode D）

Console 只做 4-node Trinity audit。其他 mode 嘅 reasoning 係 skill 嘅職責。

如果你想用 console 做類似嘅嘢，只係 single-mode + 4 個 LLM perspective，唔係 skill 嘅完整七階段或 SCR 結構。

---

## 何時用 Console，何時用 Skill

| 情境 | 用邊個 |
|------|-------|
| 即時對話、快速 audit | Skill |
| 需要 4 個 model 視角 | Console |
| 黑盒七階段分析 | Skill (`/blackbox`) |
| 重要 audit 想存檔 | Console (`--save`) |
| SCR 歷史人物 | Skill (`/scr`) |
| 批量處理新聞 | Console (loop) |
| 思考 + 寫文件 | Skill |
| 4 model 對同一問題嘅分歧 audit | Console |

---

## 安裝指引（簡短）

```bash
git clone <repo>
cd uruk-trinity-console
pip install -r requirements.txt
cp config/nodes.example.yaml config/nodes.yaml
cp config/.env.example config/.env
# 編輯 config/nodes.yaml 揀 model
# 編輯 config/.env 填 API key
python trinity_console.py -i "你嘅問題"
```

詳細指引見 console 入面嘅 `README.md`。

---

*(0,0,0).*
