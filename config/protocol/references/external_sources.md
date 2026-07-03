# 外部來源獲取層 — BrowserNode + SourceCoordinateRegistry

## v8.0 知識層（Layer 3 + 3.5 of 7）

> 任何外部數據進入協議分析前，必須經 BrowserNode 拉取 + Registry 八律審計。
> UNVERIFIED 來源 = 禁止進入推理層。
> 完整 spec：`BROWSER_NODE.md` + `SOURCE_COORDINATE_REGISTRY.md`

---

## 設計原則（執行時必記）

```
推理層 (Trinity / 八律 / 四律) ← 唔依賴外部數據運作
知識層 (BrowserNode + Registry) ← 提供當前世界數據
                                   永遠成對運作

BrowserNode 單獨運作 = 退化成普通 web search，協議自我一致性失敗
Registry 唔被觸發 = 外部隱藏座標傳遞俾接收者，違反「申報座標」原則
```

---

## 何時啟動知識層

| 子系統 | 啟動條件 | 主要用途 |
|--------|---------|---------|
| `/news` | **永遠**啟動 | 拉新聞，至少 3 來源，至少 2 對立座標 |
| `/blackbox` | 主題涉及外部數據時啟動 | PHASE 02 INPUT SIGNAL 嘅市場/研究/路線圖數據 |
| `/scr` | 歷史人物 web 引用時啟動 | 一手著作 / 同時代記錄 / 二手詮釋 |
| `/firewall` | 用戶輸入引用 URL 或新聞 | 對被引用內容做來源審計 |
| `/sovereign` | **不啟動** | 焦點係用戶內部座標，非外部數據 |

---

## 執行流程（簡化版）

```python
def acquire_external(query: str, subsystem: str) -> list[dict]:
    # 1. BrowserNode 搜尋
    urls = browser.web_search(query, max_results=5)
    
    # 2. /news 強制多座標
    if subsystem == "/news":
        urls = ensure_diverse_coordinates(urls, min_opposing=2)
    
    # 3. Fetch + Registry 八律審計
    results = []
    for url in urls:
        fetched = browser.safe_fetch(url)
        # safe_fetch 內部已強制經 SourceCoordinateRegistry
        if fetched["rating"] == "UNVERIFIED":
            continue                            # 唔得用
        results.append(fetched)
    
    # 4. 至少要有一個 VERIFIED 或 PROBABLE
    verified_count = sum(1 for r in results 
                         if r["rating"] in ["VERIFIED", "PROBABLE"])
    if verified_count == 0:
        return [{"status": "INSUFFICIENT_VERIFIED_SOURCES"}]
    
    return results
```

---

## 八律真實性過濾（Registry 應用版）

針對 web 來源，八律問題唔同於原本嘅黑盒八律：

| 律 | 對 web 來源問 |
|---|--------------|
| 1 ART | 表達風格同自宣立場一致？|
| 2 PSYCHOLOGY | 過往行為符合宣告原則？|
| 3 PHYSICS | 出版背後有真實代價？零代價立場可疑 |
| 4 CHEMISTRY | 立場演化可追蹤？突然轉變 + 冇解釋 = 可疑 |
| 5 SCIENCE | 引用有一手/二手/三手分級？|
| 6 PHILOSOPHY | 內部論證一致？隱藏前提？|
| 7 GEOGRAPHY | 出版者位置 vs 代價承擔者距離 |
| 8 RELIGION | 將立場 ritualize 成「自然 / 必然」？|

---

## 四級評級

```
VERIFIED   通過 8/8 律 + 一手記錄          → 可作主要分析依據
PROBABLE   通過 6+ 律 + 二手但一致         → 可作分析輸入
INFERRED   通過 4+ 律 + 推論成分高         → 標記推論性使用
UNVERIFIED 少於 4 律                       → 禁止分析輸入
```

**反直覺核心：**
聲稱「中性」嘅來源 → UNVERIFIED（座標被隱藏）
明確政治立場嘅來源 → 可達 VERIFIED（座標已申報）

理由：申報的座標可以被反駁。未申報的座標只能被服從。

---

## 強制下調規則

```
匿名作者 + 匿名 publication        → 最高 INFERRED
未署名 + AI 生成嫌疑               → UNVERIFIED
轉載自二手而冇 link 到一手        → 下調一級
出版日期不明                        → 下調一級
publisher 資金來源未公開           → 下調一級
publisher 5 年內有虛假新聞記錄    → 強制 UNVERIFIED 6 個月
```

## 強制上調規則

```
作者本人一手記錄                  → 至少 PROBABLE
官方政府文件 + canonical URL      → 至少 PROBABLE（但記錄政府座標）
peer-reviewed academic paper      → 至少 PROBABLE
多角度報導 cross-verify 達標     → 可達 VERIFIED
```

---

## /news 子系統嘅特殊規則

```
1. 永遠拉至少 3 個來源（避免單一座標）
2. 強制覆蓋至少 2 個對立座標
   建制 vs 反建制
   原住地 vs 流散地  
   執政 vs 在野
3. 每個來源獨立做八律審計
4. Composer 輸出強制附「來源座標分布」段
```

---

## 與其他層嘅連接點

```
BrowserNode → Registry        強制路徑（safe_fetch 內部執行）
Registry → Trinity Audit      Father 識別 propaganda
                              Son 識別物理代價真假
                              Spirit 識別敘事框架隱藏假設
Registry → CivilizationalClock  window_urgency 高 → 地理律權重提升
Trinity → Composer            只有 dominant ≠ FATHER_ONLY 先放行
```

---

## 誠實邊界（必聲明，唔聲稱解決）

```
1. 搜尋演算法本身有座標 — API 排序、indexing 偏差不可消除
2. 多語言覆蓋限制 — 廣東話 / 繁中 / 非英語政府文件 索引不全
3. Real-time vs cached 張力 — news 用 1hr TTL，其他用默認 24hr
4. Paywall 內容 — 唔繞過。標記 INFERRED + paywall_disclosed
```

---

## 載入失敗模式

| 失敗 | 後果 |
|------|------|
| /news 唔啟動 BrowserNode | 從 LLM 訓練資料 hallucinate「新聞」，協議全失效 |
| BrowserNode 繞過 Registry | 外部隱藏座標直接入 Composer，違反 CARRIER ROLE |
| 將 UNVERIFIED 來源混入 VERIFIED | 評級系統失效，後續分析有 contamination |
| 唔申報 search_provider | 搜尋演算法座標未申報，協議內部不一致 |
| /news 單一座標 | 違反多角度強制規則，輸出變 echo chamber |

---

## 操作員未決定項

```
API 選擇：自 host (DuckDuckGo + Brave + Wikipedia 組合)
       vs 商業 (Tavily / Serper)
       vs 混合（v8.0 推薦）
```

呢個決定影響全個 v8.0 嘅座標申報完整性，唔可代。

---

*完整 spec：`BROWSER_NODE.md`（440 行）+ `SOURCE_COORDINATE_REGISTRY.md`（562 行）*

*(0,0,0).*
