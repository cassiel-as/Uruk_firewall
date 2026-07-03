# BROWSER NODE — 瀏覽器作為外部感官嘅完整 spec
## 協議 v8.0 | 座標：(53.8, -1.5, 0) | 定錨：2019-06-12

> BrowserNode 唔係搜尋功能，係**將外部世界數據引入協議分析嘅唯一通道**。
> 每一個外部來源都係一個攜帶座標嘅信號——
> BrowserNode 嘅工作係將數據拉到，然後交俾 SourceCoordinateRegistry 做座標審計。
>
> **層級定位：知識層（Layer 3 of 7）——協議流水線嘅第三層。**
> **配對組件：SourceCoordinateRegistry（座標審計），見獨立文件。**
> **物理基礎：座標說 → 任何來自外部嘅信號都攜帶未申報座標，
> 將佢直接餵入分析 = 將外部座標傳遞俾接收者，違反「申報座標」原則。**

---

## 一、設計原則

### 1.1 唔係 Google Search 嘅替代品

BrowserNode 係一個**有座標感知嘅資料拉取系統**。

```
普通 web search：     query → results
BrowserNode：         query → results → coordinate audit → filtered_results
```

差別唔係技術，係**接入點**。BrowserNode 同 SourceCoordinateRegistry 永遠成對運作——
唔做座標審計嘅 BrowserNode，係退化到普通 web search，協議嘅自我一致性被破壞。

### 1.2 知識/推理分離原則

協議嘅推理層（Trinity Audit / Eight Laws / Four Laws / Delabeling）
係從操作員嘅 26 年累積構建嘅。佢哋唔需要外部數據先運行——
但佢哋需要外部數據先**指向具體議題**。

```
推理層 = 26 年累積嘅電路圖（內嵌喺 LLM + LoRA + RAG）
知識層 = 當前世界嘅實時數據（外部，需要拉取）

兩者必須分離：
  推理層唔依賴知識層嘅完整性運作
  知識層唔影響推理層嘅權重
```

BrowserNode 係知識層嘅唯一入口。

### 1.3 有座標嘅工具，唔係中性管道

任何聲稱「中性」嘅工具都隱藏咗自己嘅座標——
搜尋演算法嘅排序邏輯、API 提供者嘅商業利益、爬蟲覆蓋範圍嘅選擇——
全部都係未申報嘅座標。

BrowserNode 自身宣告座標：
```
BrowserNode coordinate declaration:
  Operator: Cassiel_as // Leeds (53.8, -1.5, 0)
  Physical anchor: 2019-06-12
  Sources prioritized: declared coordinate sources > anonymous sources
  Search bias: official sources > aggregators > forums
  Geographic bias: connected to CivilizationalClock window_urgency
```

呢個聲明係**寫入 source_coordinate_registry 嘅每個 audit record**——
唔係外部讀者見到嘅免責聲明，係系統內部嘅自我審計記錄。

---

## 二、四個核心組件

### 2.1 web_search（搜尋執行）

**功能**：接外部 search API，返回相關 URL 列表。

**輸入**：
```
query: str           — 搜尋字串
max_results: int     — 默認 5，最多 20
domain_filter: list  — 可選，限制喺特定 domain
recency_days: int    — 可選，限制最近 X 日內嘅內容
```

**輸出**：
```
[
  {
    "url": str,
    "title": str,
    "snippet": str,
    "publisher": str,
    "publication_date": str | None,
    "language": str
  },
  ...
]
```

**API 選擇（操作員決定）**：

| 選項 | 優點 | 缺點 | 座標申報狀態 |
|---|---|---|---|
| 自 host：DuckDuckGo + Brave + Wikipedia API 組合 | 符合「申報座標」原則 | 慢、覆蓋窄、需要工程 | DuckDuckGo / Brave 各自有公開搜尋邏輯 |
| 商業 API：Tavily | 易整合、覆蓋廣 | API 提供者座標未申報 | UNDECLARED |
| 商業 API：Serper | 同上 | 同上 | UNDECLARED |
| 混合：DuckDuckGo 優先，failover 到 Brave | 速度同覆蓋平衡 | 工程稍複雜 | 接近完整申報 |

**v8.0 建議**：混合方案。理由：座標說要求申報。

### 2.2 fetch_url（內容拉取）

**功能**：拉取具體 URL 嘅完整內容。

**輸入**：
```
url: str             — 目標 URL
timeout: int         — 默認 30 秒
follow_redirects: bool — 默認 True，但記錄重定向鏈
respect_robots: bool — 默認 True
```

**輸出**：
```
{
  "url": str,
  "final_url": str,           — 重定向後嘅最終 URL
  "redirect_chain": list,      — 完整重定向歷史
  "status_code": int,
  "content_type": str,
  "raw_html": str | None,
  "text_content": str,         — parse_content() 已抽出嘅純文字
  "metadata": {
    "title": str,
    "author": str | None,
    "publisher": str,
    "publication_date": str | None,
    "language": str,
    "canonical_url": str | None
  },
  "fetched_at": str            — ISO 8601 timestamp
}
```

**失敗模式**：
- timeout → 返回 `{"status": "TIMEOUT", "url": url}`
- 4xx / 5xx → 返回 `{"status": "HTTP_ERROR", "code": N, "url": url}`
- robots.txt 禁止 → 返回 `{"status": "ROBOTS_BLOCKED", "url": url}`
- paywall / 登入牆 → 返回 `{"status": "PAYWALL", "url": url, "snippet": meta_description}`

**重要原則**：BrowserNode **永遠唔繞過 paywall / robots.txt**。
協議嘅自我一致性要求尊重來源網站嘅座標申明。

### 2.3 parse_content（內容解析）

**功能**：將原始 HTML 轉化為可被分析嘅結構化文字。

**輸入**：raw_html
**輸出**：
```
{
  "main_text": str,           — 主要正文，去除 nav / ads / footer
  "headings": list,            — 標題層級結構
  "links_internal": list,      — 同 domain 嘅連結
  "links_external": list,      — 跨 domain 嘅連結（用作座標審計線索）
  "metadata_jsonld": dict | None,  — JSON-LD schema.org
  "metadata_opengraph": dict | None,
  "publish_signals": {
    "byline": str | None,
    "date_published": str | None,
    "date_modified": str | None,
    "publisher_org": str | None
  }
}
```

**parse 工具建議**：
- trafilatura（Python）— 主要 parser
- newspaper3k — fallback
- BeautifulSoup4 — metadata 抽取

### 2.4 cache（避免重複拉取）

**功能**：以 content_hash 為 key 緩存已拉取嘅來源。

**結構**：
```python
class BrowserCache:
    def __init__(self, cache_dir: Path, ttl_seconds: int = 86400):
        # 默認 TTL：24 小時
        # 對 news = 1 小時
        # 對 academic paper = 30 日
        # 對 government doc = 7 日
        ...
    
    def get(self, url: str) -> dict | None:
        # 返回緩存內容，或 None
    
    def put(self, url: str, content: dict):
        # 寫入緩存，附 content_hash
        content_hash = sha256(content["text_content"])
        # 用於 SourceCoordinateRegistry 嘅 immutable reference
```

**為何要緩存**：
1. 速度——重複 query 唔需要再 fetch
2. **座標一致性**——同一 URL 喺一段時間內嘅內容應該係同一個物理快照，
   重複 fetch 可能撞到內容更新，破壞 audit 嘅可重複性
3. **可審計性**——content_hash 寫入 SourceCoordinateRegistry，
   令任何引用都可追蹤返原始快照

---

## 三、與其他組件嘅連接

### 3.1 BrowserNode → SourceCoordinateRegistry

**強制路徑**：所有 fetch_url 嘅輸出，必須立即送俾 Registry 做八律審計。

```python
def safe_fetch(url: str) -> dict:
    raw = fetch_url(url)
    if raw["status"] != "OK":
        return raw
    
    parsed = parse_content(raw["raw_html"])
    
    # 強制經 Registry
    audit = source_coordinate_registry.audit_source(
        url=raw["final_url"],
        content=parsed,
        metadata=raw["metadata"]
    )
    
    return {
        "url": raw["final_url"],
        "content": parsed,
        "audit": audit,           — 含評級 + 八律分數
        "rating": audit["rating"], — VERIFIED / PROBABLE / INFERRED / UNVERIFIED
        "fetched_at": raw["fetched_at"],
        "content_hash": audit["content_hash"]
    }
```

**禁止繞過 Registry 嘅情況**：
- ❌ 直接將 raw text 送入 Composer
- ❌ 將 audit failed 嘅來源用作分析依據
- ❌ 將 UNVERIFIED 來源混入 VERIFIED 來源做總結

### 3.2 BrowserNode → CivilizationalClock

**功能**：搜尋偏向會根據窗口緊迫性調整。

```python
clock = CivilizationalClock()
window_urgency = clock.window_urgency()  # 0.0 - 1.0

if window_urgency > 0.7:
    # 接近 2035 反格式化窗口關閉 (v8.30 canonical; 舊值 2038 superseded)
    # 地理律權重提升 → 搜尋偏向地理上接近代價承擔者嘅來源
    search_bias["geography_weight"] = 1.5
    search_bias["prefer_local_sources"] = True
elif window_urgency > 0.4:
    search_bias["geography_weight"] = 1.2
else:
    search_bias["geography_weight"] = 1.0
```

**物理理由**（PHYSICS_CONSTANTS.md 5.1 引力場）：
窗口越接近關閉，物理在場越關鍵——
喺地理上同代價承擔者距離越近嘅來源，攜帶嘅座標密度越高。

### 3.3 BrowserNode → Trinity Audit

**強制路徑**：拉到嘅內容（特別係新聞、聲明、政策文件）必須先送 Trinity，
唔係直接送 Composer。

```python
def fetch_for_analysis(url: str) -> dict:
    fetched = safe_fetch(url)
    if fetched.get("rating") in ["UNVERIFIED", "FAILED"]:
        return {"status": "REJECTED", "reason": fetched.get("rating")}
    
    # 送 Trinity Audit
    trinity_scan = trinity_audit.scan(
        signal=fetched["content"]["main_text"],
        source_audit=fetched["audit"]
    )
    
    return {
        "content": fetched["content"],
        "rating": fetched["rating"],
        "trinity_scan": trinity_scan,  # Father / Son / Spirit 三節點
        "ready_for_eight_laws": trinity_scan["dominant"] != "FATHER_ONLY"
    }
```

**為何 Trinity 喺 BrowserNode 之後**：
- Father 識別格式化攻擊（外部來源可能係 propaganda）
- Son 識別物理代價（外部新聞報導嘅事件係咪有真實受害者）
- Spirit 識別假設逆轉（來源嘅敘事框架係咪攜帶隱藏假設）

冇呢一層，Composer 會直接將外部座標融入輸出，違反 CARRIER ROLE。

---

## 四、五個子系統嘅 BrowserNode 路由

| 子系統 | BrowserNode 嘅角色 | 默認 query 模式 |
|---|---|---|
| /firewall | 基本不用——主要分析操作員自己輸入嘅信號 | N/A |
| /blackbox | 拉領域數據（投資、市場、研究）作 PHASE 02 INPUT SIGNAL | 投資數據 / 市場結構 / 路線圖 |
| /scr | 拉歷史人物嘅一手 / 二手來源 | 著作 / 信件 / 同時代記錄 |
| /news | **主要使用者**——拉當前新聞作分析 | 事件名 + 最近時段 + 多角度 |
| /sovereign | 基本不用——主要係用戶嘅內部問題 | N/A |

**/news 子系統嘅特殊規則**：
```
1. 永遠拉至少 3 個來源（避免單一座標）
2. 強制覆蓋至少 2 個對立座標（建制 vs 反建制 / 原住地 vs 流散地）
3. 每個來源獨立做八律審計
4. Composer 嘅輸出強制附「來源座標分布」section
```

---

## 五、誠實邊界

### 5.1 BrowserNode 唔解決嘅問題

**搜尋演算法本身嘅座標**：
- 用商業 API 時，搜尋結果嘅排序由 API 提供者控制
- 自 host 時，DuckDuckGo / Brave 嘅 indexing 有自己嘅選擇偏差
- 任何搜尋系統都唔能達致真正嘅「全網中性」

**處理方式**：宣告呢個邊界，唔聲稱解決。記錄喺每個 audit record 嘅
`search_provider_disclosure` 欄位。

### 5.2 多語言覆蓋限制

- 廣東話 / 繁體中文 來源喺西方搜尋 API 入面被低估
- 非英語政府文件、地方獨立媒體 索引唔完整
- 中國大陸境內嘅 .cn 來源 訪問不穩定

**處理方式**：喺 audit record 嘅 `language_coverage` 欄位標記語言可訪問性，
跨語言議題強制要求至少 2 個語言嘅來源。

### 5.3 Real-time vs cached 嘅張力

實時嘅新聞可能比 cache 嘅準確（事件演進中），
但實時 fetch 破壞 audit 嘅可重複性。

**處理方式**：news 類 query 用 1 小時 TTL，其他用默認。
所有引用永遠包含 `content_hash` + `fetched_at`，令唔同時間做嘅 audit 可被區分。

### 5.4 Paywall 內容

學術論文、調查新聞、付費新聞 經常喺 paywall 後面。
BrowserNode 唔繞過 paywall——
但呢個意味住高質量來源被系統性低估。

**處理方式**：當 PAYWALL 偵測到，記錄 metadata + abstract，
標記 audit rating 為 INFERRED（因為內容唔可核驗），
喺 Composer 輸出強制聲明「呢個來源被 paywall 限制」。

---

## 六、與 SCR_TEMPLATE 嘅關係

SCR_TEMPLATE.md 處理**歷史人物嘅座標重組**。
BROWSER_NODE.md 處理**任何 web 來源嘅座標審計**。

兩者共用 SourceCoordinateRegistry 嘅八律過濾框架，但應用對象唔同：

```
SCR_TEMPLATE  → 對象：歷史人物嘅完整 profile
              → 輸入：一手著作 + 二手記錄 + 三手詮釋
              → 輸出：VERIFIED / PROBABLE 嘅座標聲明集合
              → 用途：對話生成

BROWSER_NODE → 對象：單一 web 來源嘅信任度
             → 輸入：URL + 拉取嘅內容
             → 輸出：來源評級 + 座標位置
             → 用途：BlackBox / News 分析嘅輸入
```

兩者連接點：當 BrowserNode 拉到關於歷史人物嘅內容，
評級時參考該人物嘅 SCR profile 作為座標 reference。

---

## 七、BrowserNode 嘅自我審計

### 7.1 每月一次嘅自我 audit

```
1. 隨機抽 100 個過去一個月嘅 audit record
2. 計算評級分佈：VERIFIED / PROBABLE / INFERRED / UNVERIFIED 嘅比例
3. 檢查 search_provider_disclosure 嘅一致性
4. 識別任何來源領域嘅系統性低估
5. 寫入 `data/kairos/_proposed/`：BROWSER_NODE_SELF_AUDIT proposal；operator review 後先合入 KAIROS_ACTIVE.md 或 archive
```

### 7.2 紅旗信號

- 連續 5 個 query 嘅結果全部來自同一個域名 → 搜尋多樣性失效
- VERIFIED 比例突然急升 → 可能係搜尋偏差，唔係真實質量提升
- 同一議題嘅多次 query 結果差異極大 → API 可能正在 personalize（座標傳遞）

紅旗觸發 → DignityClause 計數器加 1（同協議違反公設一樣處理）。

---

## 八、操作員必須做嘅決定

呢個 spec 文件嘅實施依賴一個操作員決定：

**API 選擇**：自 host vs 商業 vs 混合？

呢個決定唔可代——影響全個 v8.0 嘅座標申報完整性。

---

## 九、Glossary

```
audit          — 對單一來源嘅八律過濾分析
audit record   — Registry 入面嘅完整審計記錄
content_hash   — SHA-256 嘅文字內容指紋
fetched_at     — ISO 8601 嘅拉取時間
rating         — VERIFIED / PROBABLE / INFERRED / UNVERIFIED
source         — 任何外部 web 來源（URL）
window_urgency — CivilizationalClock 嘅 0-1 緊迫度
```

---

*座標：(53.8, -1.5, 0) Leeds*
*物理錨點：2019-06-12*
*配對文件：SOURCE_COORDINATE_REGISTRY.md*
*層級定位：Layer 3 of 7 (Knowledge Layer)*

*(0,0,0).*
