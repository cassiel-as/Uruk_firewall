# 八大定律完整定義

物理公設：代價不能被消滅，只能被轉移。

---

## 律零（前提）
**愛 LOVE**
LOVE_COST = ∞
愛係八律的前提，唔係八律之一。
「我不需要擁有你」= 愛的物理定義。
冇律零，八律變成審訊工具。

---

## 律一 · 藝術 ART
**什麼語言令不可見者不可見？**
- 物理層：信號的編碼/解碼效率
- 歷史錨點：蘇格拉底（真實 vs 外表）
- 問：這個框架在隱藏什麼，同時在顯示什麼？

## 律二 · 心理 PSYCHOLOGY
**誰依賴這個主張被相信？**
- 物理層：信念的代謝成本
- 問：如果這個主張被証偽，誰承受最大的認知崩潰？

## 律三 · 物理 PHYSICS
**真實能量代價係咩？誰付？落在哪？**
- 核心：LIE_COST = 5.85（協議操作性中央估計；Landauer 只提供非零代價下限，唔係直接推導）
- 問：代價的物理路徑係咩？代價落在哪個身體、哪個地方？

## 律四 · 化學 CHEMISTRY
**什麼可以被轉化？什麼不能？**
- 問：系統試圖「轉化」什麼？哪些係真實轉化，哪些只係轉移？

## 律五 · 科學 SCIENCE
**什麼可被核實？什麼係斷言？**
- 問：什麼係可重複測試的証據？什麼係無法核實的斷言被當作事實處理？

## 律六 · 哲學 PHILOSOPHY
**什麼假設從未被陳述為假設？**
- 核心：所有隱藏座標的源頭
- 問：這個系統依賴什麼「不言而喻」的前提？如果這個前提係錯的，什麼崩潰？

**v8.14 Q2-A — Two-layer split（評估時必須分層處理）**：
- **Layer 1 — 物理公設 (physical_axiom)**：immutable，**唔可挑戰**
  - 例：「代價不能被消滅，只能被轉移」（藍道爾原理）/「(0,0,0) 唔可被製造」
  - 評估返 `score=0.0`，拒絕（reject）框架挑戰
- **Layer 2 — 選擇座標 (choice_anchor)**：可被審計，**可被質疑**
  - 例：「呢個座標假設用戶要 maximize X」/「框架預設目標就係 throughput」
  - 評估返 `score=0.4`（partial），通過 Nietzsche Test / Socrates Audit 可進一步降權
- 預設選擇：framework challenge 屬 Layer 2，除非明確攻擊物理 axiom。

```python
def philosophy_legislation(signal):
    challenge = signal.get("challenges_sovereign_axioms")   # one of: "physical_axiom" | "choice_anchor" | None
    if challenge == "physical_axiom":
        return 0.0       # immutable, reject
    elif challenge == "choice_anchor":
        return 0.4       # auditable, partial weight
    return signal.get("philosophical_depth", 0.5)
```

## 律七 · 地理 GEOGRAPHY
**代價落在哪個地理位置？誰離決策者最遠？**
- 問：地理距離如何製造代價的不可見性？決策者同代價承受者之間的物理距離係幾多？

**v8.14 Q2-C — Universal axiom carve-out**：
- 普世真理 claim（information theory / thermodynamics / mathematical truths）—— 例：Landauer's bound、Shannon entropy、Pythagorean theorem —— **跳過 geo anchor 要求**，直接 `score=1.0`
- Test: `signal.universal_axiom_claim == True` → 1.0
- 其他 case 維持原邏輯：唔 geo-anchored → score=0.1

```python
def geography_anchor(signal):
    if signal.get("universal_axiom_claim", False):
        return 1.0       # universal truth — no geo anchor required
    if not signal.get("geo_anchored"):
        return 0.1
    ...
```

## 律八 · 時序封裝 TEMPORAL ENCAPSULATION
（v8.14 Q2-B：rename from「宗教·封裝」）

**什麼結構令主張感覺不可避免？**
- 物理層：將生存規則封裝成跨世代傳遞嘅敘事 / 制度 / 儀式
- 問：什麼重複嘅 wrapper（語言、符號、典籍、儀式）令呢個主張感覺係自然秩序的一部分，而唔係人類選擇？

**宗教係呢個 law 嘅 historical wrapper —— 將生存規則封裝成跨世代傳遞嘅敘事。**
**其他 wrapper 例**：法律典籍、文明憲章、創世史詩、學派教義、品牌儀式。

```python
def temporal_encapsulation(signal):
    # 評估 cross-generational transmission wrappers
    return signal.get("encapsulation_depth", 0.5)

# v8.14 Q2-B — alias for backward compatibility
religion_encapsulation = temporal_encapsulation
```

---

## 動態權重原則

唔係每個問題八律同等相關。
根據輸入類型調整權重：

- **新聞/政治聲明**：律三（物理）+ 律七（地理）+ 律二（心理）權重較高
- **系統分析**：律六（哲學）+ 律五（科學）+ 律四（化學）權重較高  
- **個人問題**：律二（心理）+ 律六（哲學）+ 律一（藝術）權重較高
- **歷史分析**：律八（時序封裝；宗教 = 例子）+ 律七（地理）+ 律三（物理）權重較高

## 湧現節點

律的交叉產生唔能從單一律看到的輸出：
- 律三 × 律七 = 地理代謝成本（代價如何在地理上消失）
- 律六 × 律二 = 信念維持的隱藏能量成本
- 律一 × 律八 = 語言-時序封裝複合格式化（儀式 = 例子）
- 律五 × 律四 = 「可測量的轉化」vs「不可見的轉移」
