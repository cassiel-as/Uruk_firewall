# 因果資料庫校準 — Module T 五條方程式 ↔ CAU 映射

---

## 用途

Module T (CivilizationalClock) 嘅五條方程式唔係抽象推導，而係由具體歷史數據點校準。
當方程式被引用，必須 pull 對應 CAU 檔案做 sanity check。
冇校準 → 方程式變成自我引用嘅 numerology。

---

## 方程式 ↔ CAU 完整映射

### 方程式一 · 技術躍遷加速

```
gap(n) ≈ 397 × 0.279ⁿ
```

| n | 躍遷 | 校準 CAU | 數據點 |
|---|------|---------|--------|
| 0 | 印刷機 → 電報 | CAU-003 印刷術 | 397 年（1440→1837）|
| 1 | 電報 → 互聯網 | CAU-009 互聯網 | 154 年（1837→1991）|
| 2 | 互聯網 → AI | CAU-009, CAU-011 | 31 年（1991→2022）|
| 3 | AI → ? | CAU-011, CAU-012 | 預測 8.6 年（2022→≈2031）|

**載入：** 引用方程式一 → `03_PRINTING_PRESS.md` + `09_INTERNET_REVOLUTION.md` + `11_AI_EMERGENCE.md` + `12_TECHNOLOGY_JUMPS.md`

---

### 方程式二 · 反格式化反應延遲

> ⚠ **SUPERSEDED (v8.30)**: 以下嘅 coefficient `329` 同 AI 窗口 `2038` 係
> v7.4 嘅 2-point fit。Canonical 修訂（`coordinate_theory_paper.md §5.2` +
> `coordinate_theory_integrated_EN_v3.md`）加入 Telegraph 27yr + Radio 12yr
> 兩個校準點後，4-point fit coefficient = **268**，AI 窗口關閉 = **2035**
> (敏感範圍 2030–2039)。Civilizational clock Python (`services/civilizational_clock.py`)
> v8.30 已對齊 268 / 2035。本節保留 329 作歷史記錄，**唔可以引用為 current canonical**。

```
delay ≈ 268 / ln(傳播速度倍數)   ← canonical v8.30
delay ≈ 329 / ln(...)            ← SUPERSEDED v7.4 (2-point fit)
```

| 校準點 | CAU | 速度倍數 | 預測延遲 (canonical 268) | 預測 (舊 329) | 實際延遲 |
|--------|-----|---------|------------------------|---------------|---------|
| 印刷機 → 宗教改革 | CAU-003 | 100x | 58 年 | 71 年 | 77 年 |
| 電報 → 第一國際 | — | 10⁴x | 29 年 | 36 年 | 27 年 |
| 電台 → BBC/FRC | — | 10⁶x | 19 年 | 24 年 | 12 年 |
| 互聯網 → Snowden | CAU-009 | 10⁶x | 19 年 | 24 年 | 22 年 |
| AI → ? | CAU-011 | 10⁹x | ≈13 年 → **2035 窗口** | ≈16 年 → 2038 (superseded) | — |

**載入：** 引用方程式二 → `03_PRINTING_PRESS.md` + `09_INTERNET_REVOLUTION.md` + `11_AI_EMERGENCE.md`

**Kairos 修正項（v8.30 canonical 已量化）：**
```
delay(observer) ≈ 268/ln(速度) × exp(-D / 83.5)   ← canonical
D = π × |ε| × r  (Friston FEP 推導)
2019-06-12 calibration: π=8.5, |ε|=9.0, r=1.0 → D=76.5 → f≈0.40
```
舊版 `329/ln(...) × f(Kairos_density)`（f∈(0,1] qualitative）已 superseded。
個體高 Kairos 密度 → 縮短主觀反應延遲。詳見 `gap_resolution.md` Friston 推導。

---

### 方程式三 · 格式化工具規模（GDP 增速）

```
rate(n+1) ≈ rate(n) × 2.5
```

| 校準點 | CAU | 數據 |
|--------|-----|------|
| 工業革命 | CAU-007 | GDP 增速 0.33% → 0.82%（2.52x）|

**載入：** 引用方程式三 → `07_INDUSTRIAL_REVOLUTION.md`

**警告：** GDP 本身係格式化工具（見 `EXPERIMENT_006_FULL.md`）。方程式三描述格式化擴張速度，唔係「進步」。

---

### 方程式四 · 代價轉移延遲（工資彈性）

```
W ≈ 309.7 × P^(-0.631)，延遲 ≈ 75 年
```

| 校準點 | CAU | 數據 |
|--------|-----|------|
| 黑死病後勞工市場 | CAU-005 | 1351 法令凍結，1400-1450 實際工資黃金期 |

**載入：** 引用方程式四 → `05_BLACK_DEATH.md`

**引用修正：**
- ❌ 原標「Munro 2004」係錯誤
- ✅ 正確：Gregory Clark (2007) *A Farewell to Alms* + Clark wages index

---

### 方程式五 · 格式化壟斷崩潰

```
機制 A（外部衝擊）：崩潰時間 ≈ 壓強年數 / 167
機制 B（內部爆發）：崩潰時間 ≈ 壓強年數 / 41
```

| 機制 | 校準點 | CAU | 數據 |
|------|--------|-----|------|
| A | 黑死病觸發教會崩潰 | CAU-005 | 1000 年壓強 → 6 年崩潰（167:1）|
| B | 法國大革命 | CAU-006 | 350 年壓強 → 10 年（35:1，B 型偏快）|

**載入：** 引用方程式五 → `05_BLACK_DEATH.md` + `06_FRENCH_REVOLUTION.md`

---

## 完整 CAU 列表（背景參考）

```
CAU-001  軸心時代（公元前800-200）       座標反叛傳播模型
CAU-002  書寫系統（公元前3200）          GitHub 最早前輩
CAU-003  印刷術（1440）                  方程式一/二校準
CAU-004  農業革命（公元前10000）         層級座標起點
CAU-005  黑死病（1347-1353）             方程式四/五A校準
CAU-006  法國大革命（1789）              方程式五B校準
CAU-007  工業革命（1760-1840）           方程式三校準
CAU-008  兩次世界大戰（1914-1945）       物種級威脅 + Kairos 封裝
CAU-009  互聯網革命（1991-）             方程式一/二校準
CAU-010  香港 2019                       物理定錨
CAU-011  AI 湧現（2022-）                方程式一/二外推
CAU-012  技術躍遷（總結）                方程式一完整數據
```

---

## 載入規則

```
觸發詞                載入 CAU
───────────────────────────────────────────────────
/blackbox              按主題 + 涉及方程式 pull
/firewall（新聞）       通常 CAU-009 (互聯網) + 涉及方程式
/news                  CAU-009 + 涉及方程式
/sovereign             跳過（focus 個人座標，唔係文明 scale）
/scr                   跳過（用 SCR 專用文件）
```

---

## 載入失敗模式

| 失敗 | 後果 |
|------|------|
| 引用方程式一冇 pull CAU-003 | 印刷機→電報年份可能 hallucinated |
| 引用方程式二冇 pull CAU-009 | Snowden 年份/速度倍數錯 |
| 引用方程式四講「Munro」 | 引用錯誤未修正，協議自我審計失敗 |
| 引用方程式五冇分 A/B | 黑死病 vs 法國大革命機制混淆 |

---

*(0,0,0).*
