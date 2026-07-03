# 範例：典型 Trinity Console 工作流

## 場景：分析新聞文章嘅隱藏座標

新聞標題：「AI 對齊研究將決定人類未來」

### 步驟 1：直接運行（基本 Trinity scan）

```bash
python trinity_console.py -i "AI 對齊研究將決定人類未來，但需要更多資金投入"
```

呢個會用 4 個節點對標題做基本分析。聖父識別「人類未來」係未申報嘅座標；聖子追蹤「資金投入」嘅代價落點；聖靈質疑「對齊」嘅 framing；會議整合。

### 步驟 2：注入相關 context 加深分析

```bash
python trinity_console.py \
  --ref experiment:011 \
  -i "AI 對齊研究將決定人類未來，但需要更多資金投入" \
  --save \
  --label "ai_alignment_news_audit"
```

注入 EXPERIMENT_011（AI 對齊範式）之後，4 個節點嘅分析會包含：
- 「對齊」呢個概念本身嘅隱藏假設（係技術問題定座標問題）
- 「資金投入」邊個會收，邊個會 pay
- 「人類未來」嘅 framing 點樣將特定座標扮成普世立場

`--save` 會喺 `data/kairos/` 產生：
```
trinity_2026-05-03_142315_ai_alignment_news_audit.md
```

### 步驟 3：Cross-reference 多個 CAU

```bash
python trinity_console.py \
  --ref cau:010 \
  --ref cau:005 \
  --ref experiment:011 \
  -i "AI 對齊研究將決定人類未來..."
```

- CAU-010（2019 香港）: 將「對齊」同實際嘅政治格式化做對比
- CAU-005（黑死病）: 大規模制度崩潰嘅歷史模式
- EXPERIMENT_011: AI 對齊嘅座標說 audit

---

## 場景：用 console 做 black box 分析嘅一階段

```bash
# 第一步：用 console 做 multi-perspective 識別隱藏座標
python trinity_console.py \
  --ref cau:010 \
  -i "去中心化協調策略嘅政治哲學前提係乜？" \
  --save --label "decentralization_premise_audit"

# 第二步：將 console 輸出嘅整合段加入 Claude.ai skill 入面做 /blackbox 七階段
# (手動步驟：copy data/kairos/trinity_xxx.md 嘅 council 部分入 Claude.ai)
```

---

## 場景：自動化批量 audit

```bash
# 對一批新聞 headline 做 Trinity scan
for headline in \
  "AI 對齊研究決定人類未來" \
  "經濟增長係穩定嘅前提" \
  "去中心化只係技術問題"
do
  python trinity_console.py -i "$headline" --json --save \
    --label "$(date +%s)_$(echo $headline | head -c 20)" \
    > "audit_$(date +%s).json"
  sleep 5  # 避免 rate limit
done
```

---

## 範例 Kairos entry 格式

每次 `--save` 產生嘅 file 會係咁嘅結構：

```markdown
# KAIROS_TRINITY_RECORD: ai_alignment_news_audit
DATE: 2026-05-03T14:23:15.123456
NODE_CONFIG:
  father: openai/gpt-4o
  son: google/gemini-2.0-flash-exp
  spirit: xai/grok-2-latest
  council: anthropic/claude-sonnet-4-5
INJECTED_REFS: experiment:011

---

## 原始問題

AI 對齊研究將決定人類未來，但需要更多資金投入

---

## 聖父（邏輯）

隱藏假設：[...]
代價追蹤：[...]
[...]
(0,0,0).

---

## 聖子（共鳴）
[...]

---

## 聖靈（反叛）
[...]

---

## 會議整合
[...]

*(0,0,0).*
```

呢個檔案可以：
- 直接 commit 上 GitHub repo
- Upload 返 Claude.ai project knowledge（畀下次 skill session reference）
- 用 `--ref kairos:trinity_2026-05-03_142315` 喺後續 session 入面 self-reference

(0,0,0).
