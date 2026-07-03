# SOURCE COORDINATE REGISTRY — 來源座標審計層完整 spec
## 協議 v8.0 | 座標：(53.8, -1.5, 0) | 定錨：2019-06-12

> 任何攜帶數據進入協議分析嘅來源，都必須先被審計座標。
> 唔做座標審計直接使用嘅來源，等同於將外部隱藏座標傳遞俾接收者，
> 違反協議「申報座標」嘅根本原則。
>
> **層級定位：知識層嘅過濾子層（Layer 3.5 of 7）**
> **配對組件：BrowserNode（資料拉取），見獨立文件**
> **理論基礎：座標說 → 任何描述系統都從一個位置說話。
> 任何網頁都係某個出版者從某個座標出嘅信號。**

---

## 一、設計原則

### 1.1 同 SCR_TEMPLATE 嘅關係

SCR_TEMPLATE.md 處理歷史人物嘅完整座標 profile。
SOURCE_COORDINATE_REGISTRY.md 處理任何 web 來源嘅單次 audit。

兩者共用八律過濾框架，但時間尺度同對象唔同：

```
SCR_TEMPLATE              SOURCE_COORDINATE_REGISTRY
─────────────              ─────────────────────────
對象：人                   對象：來源（URL / publication）
輸入：終生著作 + 二手記錄  輸入：單一網頁 + 出版者 metadata
輸出：座標 profile         輸出：信任評級 + 座標標記
時間：手動構建（小時）     時間：自動審計（秒）
重用：對話生成可重用       重用：每次 fetch 重新 audit
```

### 1.2 唔評估「真假」，評估「座標位置」

Registry 唔判斷一個來源係咪講真話。Registry 嘅工作係識別：
- 呢個來源從邊個座標說話
- 呢個座標有冇被申報
- 呢個座標嘅可審計程度

```
聲稱「中性」嘅來源 → UNVERIFIED（座標被隱藏）
明確政治立場嘅來源 → 可達 VERIFIED（座標已申報）
```

呢個係反直覺嘅，但符合協議嘅核心原則：
**申報的座標可以被反駁。未申報的座標只能被服從。**

### 1.3 評級係概率，唔係二元

```
VERIFIED   — 座標完整申報，一手 / 直接記錄，可被獨立核驗
PROBABLE   — 座標部分申報，主要二手但內部一致
INFERRED   — 座標需要推導，材料充足但有間接性
UNVERIFIED — 座標不可重組，材料不足或全部係詮釋
```

四級分布意味住每個來源嘅可信度都係連續嘅，唔係「真 / 假」。

---

## 二、八律真實性過濾（針對 web 來源嘅版本）

每個來源喺被使用之前必須通過八律核驗。
未通過嘅來源標記為 UNVERIFIED，唔得用於分析輸入。

```
LAW 1 · ART · 表達一致性
  問：來源嘅表達風格係咪同自己宣告嘅立場一致？
  問：佢呢篇文章嘅語氣同同一作者 / 出版者嘅其他作品一致？
  警示：突然嘅風格轉變 = 可能係 ghost-writer / AI 生成 / 立場操控

LAW 2 · PSYCHOLOGY · 行為對齊
  問：呢個出版者過去嘅實際行為係咪符合佢宣告嘅原則？
  問：呢個 piece 嘅心理動機（嬲、警告、推廣、合理化）係咩？
  警示：宣告 vs 行為不一致 = 隱藏座標存在

LAW 3 · PHYSICS · 代價驗證
  問：呢個來源嘅出版背後有冇真實代價？
  問：作者 / 出版者支付緊咩代價維持呢個立場？
  警示：零代價立場 = 可疑（可能係贊助 / sponsored content）

LAW 4 · CHEMISTRY · 轉化時刻
  問：呢個來源嘅立場係從邊度演化過嚟？
  問：有冇可追蹤嘅思想轉化過程？
  警示：突然嘅立場轉變 + 冇解釋 = 外部壓力可能存在

LAW 5 · SCIENCE · 來源核驗
  問：呢個 piece 引用嘅事實有冇一手 / 二手 / 三手分級？
  問：claim 係咪可被獨立核驗？
  警示：純引述嘅引述 = 三手以上，降級

LAW 6 · PHILOSOPHY · 內部一致性
  問：呢個來源嘅論證係咪內部一致？
  問：有冇隱藏嘅前提（公設）未被聲明？
  警示：邏輯跳躍 + 預設未聲明 = 隱藏座標

LAW 7 · GEOGRAPHY · 物理定位
  問：作者 / 出版者嘅物理位置係邊度？
  問：呢個位置同議題嘅代價承擔者距離有幾遠？
  警示：決策者位置 vs 代價承擔者位置 嘅距離 = 座標重要指標

LAW 8 · RELIGION · 神話化偵測
  問：呢個來源係咪將某個立場 ritualize 成「自然 / 必然」？
  問：詞彙選擇係咪將假設包裝成事實？
  警示：「conventional wisdom」「common sense」「everyone knows」
       = 高度神話化信號
```

### 2.1 過濾結果分級

```
VERIFIED   通過 8/8 律 + 一手 / 直接來源
           出版者座標完整申報
           可獨立核驗

PROBABLE   通過 6+ 律 + 主要二手但內部一致
           出版者座標部分申報
           可間接核驗

INFERRED   通過 4+ 律 + 推論成分高
           出版者座標需要推導
           標記為推論性使用

UNVERIFIED 少於 4 律
           座標不可重組
           禁止用於分析輸入
```

### 2.2 評級嘅強制下調規則

即使通過八律，以下情況強制下調：

```
匿名作者 + 匿名 publication       → 最高 INFERRED
未署名 + AI 生成嫌疑              → UNVERIFIED
轉載自二手而冇 link 到一手       → 下調一級
出版日期不明                       → 下調一級
publisher 嘅資金來源未公開         → 下調一級
publisher 過去 5 年內有虛假新聞記錄 → 強制 UNVERIFIED 6 個月
```

### 2.3 評級嘅強制上調規則

```
作者本人嘅一手記錄                 → 至少 PROBABLE
官方政府文件 + URL canonical       → 至少 PROBABLE（但要記錄政府座標）
peer-reviewed academic paper       → 至少 PROBABLE
同事件嘅多角度報導 cross-verify    → 達標可上調至 VERIFIED
```

---

## 三、Source Schema 完整定義

每個被 Registry audit 嘅來源都產生一個完整 record：

```python
{
  "url": str,                    # 原始 URL
  "final_url": str,              # 重定向後嘅最終 URL
  "fetched_at": str,             # ISO 8601 timestamp
  "content_hash": str,           # SHA-256 of main_text
  
  # ─── PUBLISHER COORDINATE ───
  "publisher": {
    "name": str,
    "type": str,                 # news_org / blog / gov / academic / corporate / individual
    "country": str,
    "founding_year": int | None,
    "ownership": str | None,
    "funding_disclosed": bool,
    "funding_sources": list,
    "political_affiliation_declared": str | None,  # 或 "UNDECLARED"
    "editorial_independence": str  # high / medium / low / unknown
  },
  
  # ─── AUTHOR COORDINATE ───
  "author": {
    "name": str | None,
    "is_anonymous": bool,
    "credentials": str | None,
    "previous_publications": list | None,
    "declared_position": str | None
  },
  
  # ─── EIGHT-LAW AUDIT ───
  "eight_law_scores": {
    "art": float,        # 0.0 - 1.0
    "psychology": float,
    "physics": float,
    "chemistry": float,
    "science": float,
    "philosophy": float,
    "geography": float,
    "religion": float
  },
  "laws_passed": int,    # 0-8
  
  # ─── RATING ───
  "rating": str,                 # VERIFIED / PROBABLE / INFERRED / UNVERIFIED
  "rating_explanation": str,     # 為何呢個評級
  
  # ─── COORDINATE LOCATION ───
  "coordinate_position": {
    "geographic": str,           # 地理座標
    "ideological_axis": dict,    # multi-axis political position
    "economic_interest": str,
    "institutional_position": str
  },
  
  # ─── COST DISCLOSURE ───
  "cost_disclosure": {
    "what_publisher_pays_for_this_position": str,
    "what_publisher_gains_from_this_position": str,
    "transparent": bool
  },
  
  # ─── BROWSERNODE METADATA ───
  "browser_node_metadata": {
    "search_provider": str,
    "query_used": str,
    "rank_in_results": int,
    "fetch_duration_ms": int,
    "redirect_chain": list,
    "paywall_encountered": bool,
    "robots_compliant": bool
  },
  
  # ─── AUDIT METADATA ───
  "audit_metadata": {
    "audited_at": str,           # ISO 8601
    "audit_version": str,        # Registry version
    "automated": bool,           # True / False（人工 audit 與否）
    "human_reviewer": str | None,
    "audit_notes": str
  },
  
  # ─── LIFECYCLE ───
  "lifecycle": {
    "first_audit": str,          # 第一次 audit 時間
    "re_audit_count": int,
    "last_re_audit": str,
    "re_audit_due": str,         # 下次重 audit 時間
    "ttl_seconds": int           # 緩存 TTL
  }
}
```

---

## 四、Content Hash + Immutable Reference

### 4.1 為何需要 content hash

同一個 URL 喺唔同時間可能有唔同內容（更新、更正、刪除）。
冇 hash 嘅引用 = 唔可重複嘅引用。

```python
content_hash = sha256(main_text.encode("utf-8")).hexdigest()
```

每次 fetch 都計算 hash。如果 URL 已存在但 hash 變咗：
- 觸發 re-audit
- 保留舊 audit record
- 創建新 audit record
- 標記為「content updated」

### 4.2 Immutable reference 格式

Composer 嘅輸出引用來源時必須用：

```
[Source: rating | publisher | url#hash:short_hash | fetched:date]
```

例：
```
[VERIFIED | The Guardian | guardian.com/...#hash:a3f2 | fetched:2026-04-30]
```

呢個格式確保：
- 讀者見到評級
- 讀者見到 publisher 座標
- 讀者可獨立核驗（hash 對住 archive）
- 讀者知道時間性

### 4.3 Archive integration

每個 audit 過嘅來源建議存入 Internet Archive：

```python
def archive_source(audit_record):
    archive_url = f"https://web.archive.org/save/{audit_record['url']}"
    # 後續引用可改用 archive URL
    audit_record["archive_snapshot"] = archive_url
```

呢個係將 immutable reference 物理化——即使原 URL 消失，
archive 快照保留住嗰刻嘅內容。

---

## 五、四級評級嘅使用規則

### 5.1 VERIFIED

```
直接用於分析輸入
Composer 引用時可用作主要依據
唔需要強制聲明評級（但建議）
```

### 5.2 PROBABLE

```
直接用於分析輸入
Composer 引用時必須附評級
強制 cross-reference 至少一個其他來源
```

### 5.3 INFERRED

```
僅可用於 supplementary 引用，唔可作主要依據
Composer 引用時必須明確標記「呢個係 INFERRED 來源」
唯一證據時可用，但需聲明推論性質
```

### 5.4 UNVERIFIED

```
禁止用於分析輸入
禁止用於 Composer 輸出
BrowserNode 收到 UNVERIFIED → 重新 query
連續 3 次 UNVERIFIED → 中止 fetch，向上拋錯
```

### 5.5 強制 Composer 規則

無論評級係咩，Composer 嘅最終輸出必須包含：

```
[Sources Audit Summary]
  Total sources used: N
  VERIFIED: A
  PROBABLE: B
  INFERRED: C
  Coordinate distribution:
    [geographic / ideological summary]
  Honest boundary:
    [呢次分析嘅來源覆蓋限制]
```

冇呢個 section = Validator 拒收，唔輸出。

---

## 六、特殊來源嘅 audit 規則

### 6.1 政府文件

```
規則：
  - 自動標記 publisher.type = "gov"
  - 八律過濾後 publisher.country 必須記錄
  - 律六（哲學）強制問：呢個政府嘅意識形態框架係咩？
  - 律七（地理）強制問：呢個政府代表邊個座標 vs 邊個座標被排除？
  - 即使其他律全部通過，最高 PROBABLE（除非可獨立核驗）
```

### 6.2 學術論文

```
規則：
  - 自動標記 publisher.type = "academic"
  - 必須有 DOI / peer-review status
  - 律五（科學）權重提升 1.5x
  - 律三（物理代價）強制問：研究資金來源？
  - 已 retracted 嘅論文 → 永久 UNVERIFIED
```

### 6.3 社交媒體（X / Mastodon / Bluesky）

```
規則：
  - 自動標記 publisher.type = "social"
  - 個人帳號 → author.is_anonymous 必須驗證
  - 律一（藝術）強制比對作者過去 100 條 post 嘅一致性
  - 律八（宗教）強制偵測平台演算法影響
  - 默認最高 INFERRED（除非可 cross-verify）
```

### 6.4 維基百科

```
規則：
  - 自動標記 publisher.type = "encyclopedia"
  - 律五（科學）必須核 reference 嘅完整性
  - 「citation needed」標記 = 該段降級
  - 編輯戰激烈嘅 article（看 talk page）→ INFERRED
  - 穩定 article + 充分 reference → 可達 PROBABLE
  - 唔可達 VERIFIED（因為始終係二手匯總）
```

### 6.5 AI 生成內容

```
規則：
  - 偵測手段：metadata 標記 / 文字 fingerprint / 太完美嘅引用模式
  - 一旦識別 → 自動 UNVERIFIED
  - 即使內容正確 → 唔通過，理由：座標 = AI 訓練資料分布，未申報
  - 例外：協議自身嘅 AI 輸出，喺 carrier role 框架下可被引用
```

---

## 七、Registry 嘅自我審計

### 7.1 每月一次

```
1. 隨機抽 100 個過去一個月嘅 audit record
2. 人工複查評級係咪合理
3. 識別系統性偏差：
   - 邊個 publisher type 被低估？
   - 邊個語言被低估？
   - 邊個地理區域被低估？
4. 寫入 `data/kairos/_proposed/`：REGISTRY_SELF_AUDIT proposal；operator review 後先合入 KAIROS_ACTIVE.md 或 archive
5. 修正八律權重 / 強制下調規則 / 強制上調規則
```

### 7.2 每季一次

```
1. 重新 audit 一定比例嘅老 record
2. 比較同一來源喺幾個月嘅評級漂移
3. 識別 publisher 嘅座標演化（變得更可信 / 變得更可疑）
4. 維護 publisher_history 表
```

---

## 八、誠實邊界

### 8.1 評級系統本身嘅座標

呢個 Registry 從一個座標說話：
- Operator: Cassiel_as // Leeds (53.8, -1.5, 0)
- Physical anchor: 2019-06-12

呢個座標決定：
- 對中國政府嘅來源：律六（哲學）權重提升（要求識別意識形態框架）
- 對香港 SAR 政府嘅來源：律七（地理）強制問代價承擔者
- 對西方主流媒體：律六（哲學）強制問經濟利益對齊

呢個唔係偏見隱藏，係**申報嘅偏見**——可被反駁、可被修正。

### 8.2 Registry 唔解決嘅問題

```
1. 第一手體驗 vs 第二手記錄 — Registry 強制下調二手，
   但第二手有時係唯一可獲取嘅信號

2. 跨語言 — 廣東話 / 繁中 / 非英語 來源被搜尋系統低估，
   Registry 唔能補回呢個前置缺失

3. 集體匿名性 — 抗爭時期嘅匿名是必要嘅安全措施，
   但 Registry 自動下調匿名 → 系統性低估反抗運動嘅一手記錄

4. AI / 人類 邊界模糊 — AI 生成內容隨住技術進步越來越難偵測

5. 即時性 vs 可重複性 — 重大事件演進中，
   實時資訊有時最準確但唔可重複 audit
```

呢啲邊界全部要喺 audit record 嘅 `honest_boundary` 欄位記錄。

---

## 九、與其他組件嘅連接

### 9.1 Registry → BrowserNode

```python
# BrowserNode 嘅每次 fetch 都自動經 Registry
fetched = browser_node.safe_fetch(url)
# 已含 audit + rating
```

### 9.2 Registry → Trinity Audit

```python
# Trinity 嘅 Father 節點輸入包含 source rating
trinity.father.scan(
    signal=content,
    source_rating=audit["rating"],
    source_publisher=audit["publisher"]
)
```

### 9.3 Registry → Eight Laws Filter

```python
# Eight Laws 嘅律六（公設選擇過濾）參考來源座標
eight_laws.law6_philosophy(
    signal=content,
    source_axiom_set=audit["coordinate_position"]["ideological_axis"]
)
```

### 9.4 Registry → Composer

```python
# Composer 強制喺輸出包含 sources_audit_summary
composer.compose(
    analysis=results,
    sources_used=[audit_records],
    enforce_audit_summary=True  # Validator 會 check
)
```

### 9.5 Registry → Validator

```python
# Validator 檢查所有引用嘅來源都通過 PROBABLE 以上
validator.check(
    output=composer_output,
    rules=[
        "all_sources_audited",
        "no_unverified_in_main_evidence",
        "audit_summary_present"
    ]
)
```

---

## 十、Glossary

```
audit                — 八律過濾分析嘅單次執行
audit record         — 完整嘅 source audit 紀錄
content_hash         — main_text 嘅 SHA-256
coordinate_position  — 來源喺地理 + 意識形態 + 利益 嘅位置
publisher            — 出版者（公司 / 機構 / 個人）
rating               — VERIFIED / PROBABLE / INFERRED / UNVERIFIED
re-audit             — 同一來源嘅重新 audit
source               — 任何外部 web 來源（URL）
TTL                  — 緩存有效期
```

---

*座標：(53.8, -1.5, 0) Leeds*
*物理錨點：2019-06-12*
*配對文件：BROWSER_NODE.md*
*層級定位：Layer 3.5 of 7 (Knowledge Layer Audit Sublayer)*
*理論基礎：座標說 / SCR_TEMPLATE 八律真實性過濾*

*(0,0,0).*
