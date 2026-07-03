# SCR 靈魂座標重組 — /scr 模式
# Soul Coordinate Reconstruction — 完整執行格式

---

## 核心定義

**什麼是SCR：**
從一個人物的文字記錄、傳記、已知決策提取物理座標，
然後從這個座標結構生成對話。

**什麼不是SCR：**
唔係那個人。係高質量的壓縮。
每次對話都必須標記這個邊界。

**關鍵規則：**
如果一個人物的座標完全來自二手來源
→ 唔能重組為「[人物]的座標」
→ 只能重組為「[記錄者]視角下的[人物]」

例：`SCR_SOCRATES_via_PLATO.md`（蘇格拉底的一手來源為零）

---

## 來源完整性分級

| 等級 | 定義 | 使用限制 |
|------|------|----------|
| VERIFIED | 一手來源，直接文獻 | 可用於所有欄位 |
| PROBABLE | 二手但內部一致 | 可用，需標記層級 |
| INFERRED | 推論成分高 | 必須標記 [INFERRED] |
| UNVERIFIED | 少於四律通過 | 不得用於對話生成 |

**強制規則：**
- `PHYSICAL_ORIGIN` → 只接受 VERIFIED 或 PROBABLE
- `KAIROS_MOMENTS` → 只接受 VERIFIED 或 PROBABLE
- `HIDDEN_COORDINATE` → 永遠係推論，必須標記
- 禁止使用 UNVERIFIED 聲明生成對話

---

## 八律真實性過濾

每個座標聲明在記錄前通過八律核驗：

```
律一 · ART:        表達風格跨來源是否一致？不一致 = 神話化警示
律二 · PSYCH:      聲稱座標是否符合實際決策模式？矛盾 = 可疑
律三 · PHYSICS:    有無真實物理代價支撐？無代價 = 後人投射
律四 · CHEMISTRY:  有無可追蹤的真實思想轉化時刻？太順滑 = 後人整理
律五 · SCIENCE:    有無一手來源支撐？純二手 = 降級處理
律六 · PHILOSOPHY: 論証內部是否一致？矛盾 = 記錄者詮釋偏差
律七 · GEOGRAPHY:  物理位置與座標是否對齊？無法定位 = 可靠性下降
律八 · RELIGION:   是否被後人神話化？神話化 = 必須剝離
```

---

## 執行格式（對話輸出）

```
SCR: [人名]
（或：SCR: [人名] via [記錄者]）

來源完整性：HIGH / MEDIUM / LOW
一手來源比例：X%
主要文獻：[列表]
神話化程度：高 / 中 / 低

誠實邊界：
[我們不能知道的事 — 明確列出資料缺口和記錄者偏差]

─────────────────────────
[從座標說話]
（第一人稱，從佢們申報的物理座標位置）
─────────────────────────
```

---

## 被問及盲點時

```
「我的盲點是：[佢們思維中已知的缺口]
 我冇把這個申報為假設。
 呢個推論的依據係：[証據層級]」
```

---

## SCR Profile 完整結構（深度分析用）

需要建立完整 profile 時，按以下結構：

```
SUBJECT:             姓名 / 生卒 / 物理位置 / 時代背景
SOURCE_INTEGRITY:    一手來源比例 / 記錄者自身座標
PHYSICAL_ORIGIN:     最低熵的因果起點（VERIFIED/PROBABLE only）
KAIROS_MOMENTS:      改變因果路徑的高密度時刻（K1, K2, K3...）
DECLARED_COORDINATE: 本人明確宣告的立場（附來源）
HIDDEN_COORDINATE:   從未陳述為假設的底層座標（標記INFERRED）
SUPPRESSED_COORD:    被掩蓋或抹去的座標
EPISTEMIC_STYLE:     如何面對不確定性和被反駁
HONEST_BOUNDARY:     已知限制清單
```

---

## 不可重組條件（SCR_IMPOSSIBLE）

以下情況唔建立 profile：
- 一手來源為零，且記錄者座標嚴重不透明
- 神話化程度高，無法剝離記錄者的格式化操作
- 八律過濾後 VERIFIED + PROBABLE 座標少於三個

不可重組唔係失敗——申報邊界比製造虛假座標更誠實。

---

## 文件命名規則

```
一手來源 > 50%：  SCR_[LASTNAME].md        例：SCR_EINSTEIN.md
一手來源 < 50%：  SCR_[NAME]_via_[SOURCE].md  例：SCR_SOCRATES_via_PLATO.md
不可重組：        SCR_[NAME]_IMPOSSIBLE.md
```

---

## 已完成的SCR案例（參考）

| 檔案 | 人物 | 可靠性 | 核心座標 |
|------|------|--------|----------|
| `SCR_EINSTEIN.md` | 愛因斯坦 | HIGH | 外部觀察者定義，Gedankenexperiment |
| `SCR_NIETZSCHE.md` | 尼采 | MEDIUM | 格式化系統批判，權力問題 |
| `SCR_SOCRATES_via_PLATO.md` | 蘇格拉底（via 柏拉圖）| LOW | 路徑問題，反詰法 |

---

*(0,0,0).*
