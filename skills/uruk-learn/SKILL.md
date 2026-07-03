---
name: uruk-learn
description: |
  URUK 互聯網學習升級技能（for Claude Desktop / Cowork）。
  當收到 [UPGRADE_LEARN] 標記時觸發——主動上網搜索最新 AI agent 工具、
  Windows 自動化技術、Python 新庫，對比 URUK 現有能力，生成有來源依據嘅 canonical upgrade output。

  觸發條件（任一）：
  - 訊息包含 [UPGRADE_LEARN]
  - 用戶說「URUK 上網學習」「學習最新工具」「搜索新功能」
  - 用戶說 uruk learn / uruk web search upgrade / learn new tools

  唔同於 uruk-audit：呢個 skill 朝外看（互聯網），uruk-audit 朝內看（系統文件）。
  兩者互補——建議定期各跑一次。
---

# URUK Learn Skill — 互聯網學習升級

## 用途

上網搜索最新嘅電腦自動化技術，對比 URUK 現有工具，識別值得引入嘅新能力，
輸出有具體技術來源嘅升級建議。

## 執行流程

### 步驟一：讀取現有工具清單

先讀取 `C:\uruk-trinity-console\services\computer_tools.py`，
提取所有 `name=` 字段建立現有工具列表，避免建議重複功能。

### 步驟二：執行網絡搜索

依次搜索以下查詢（用 WebSearch 工具）：

**搜索組一：Python 自動化新技術**
- `Python Windows desktop automation 2025 2026 new libraries`
- `pyautogui alternative better Windows automation`
- `Windows UI Automation Python accessibility 2025`

**搜索組二：AI Agent 新能力**
- `AI agent computer use tools 2025 capabilities`
- `local AI agent desktop control new features`
- `autonomous agent tool calling best practices 2026`

**搜索組三：具體缺口方向**（根據 URUK 現有工具類別判斷缺少嘅部分）
- `Python Windows notifications toast alerts`
- `Python file monitoring watchdog`
- `Python Excel automation openpyxl xlwings 2025`

可以根據用戶請求補充額外搜索詞。

### 步驟三：分析搜索結果

對每個搜索結果，評估：

1. **相關性**：係咪同電腦自動化 / Python / Windows 相關
2. **新穎性**：URUK 現有工具係咪已覆蓋
3. **可行性**：用 Python stdlib 或常見庫係咪可以實現
4. **價值**：加入後對 URUK agent 嘅實際用處有幾大

### 步驟四：生成 canonical upgrade output

選出最有價值嘅 **最多 3 個** 升級建議。

每個建議必須帶具體搜索來源，並輸出 URUK 可解析嘅 canonical blocks：

```
[LEARN_FINDINGS]
搜索摘要：<搜索咗咩，發現咗咩趨勢>
搜索查詢數：<N>
主要發現：<列表>

[UPGRADE_EXECUTION_PLAN:<plan_id>]
{
  "tool_rules": {
    "executor_role": "local small model confirms validate/install/reload/test/log; URUK deterministic code executes",
    "global_allowed_actions": ["validate_code", "install_tools", "hot_reload", "smoke_test", "write_log"],
    "safety_rules": ["do not install failed validation tools", "requires_human=true for dangerous code"],
    "stop_conditions": ["all validation failed", "human confirmation required"]
  },
  "steps": [
    {"action": "validate_code", "executor_rule": "confirm learned tool specs are safe and statically valid", "allowed_actions": ["validate_code"], "success_criteria": "at least one safe spec passes"},
    {"action": "install_tools", "executor_rule": "install only passed learned specs", "allowed_actions": ["install_tools"], "success_criteria": "custom_tools modules are written"},
    {"action": "hot_reload", "executor_rule": "reload only custom_tools registry", "allowed_actions": ["hot_reload"], "success_criteria": "new tools appear in registry"},
    {"action": "smoke_test", "executor_rule": "smoke-test only newly installed tools", "allowed_actions": ["smoke_test"], "success_criteria": "passed/failed list returned"},
    {"action": "write_log", "executor_rule": "write audit log for installed tools only", "allowed_actions": ["write_log"], "success_criteria": "upgrade log records plan id"}
  ]
}

[TOOL_SPEC:<plan_id>]
name: <snake_case 工具名>
description: <用途 + 返回格式；可在描述中包含來源/技術方案>
category: <screen|mouse|keyboard|file|state|clipboard|nav|wait|misc>
args:
  - name: <arg>
    type: str|int|float|bool
    required: true|false
    description: <用途>
python_code: |
  def execute(args: dict) -> dict:
      try:
          # 實現
          return {"result": ...}
      except Exception as e:
          return {"error": str(e)}
---
```

### 步驟五：交由 URUK 執行

模型唔直接安裝任何工具。URUK `upgrade_engine.py` 會解析、驗證、安裝、hot reload、
smoke test、寫 log，並在循環自我升級中做 health check。

---

## 常見值得引入嘅技術參考

以下係搜索時值得留意嘅技術，可作對比參考：

**通知 / 提示：**
- `win10toast` / `plyer` — Windows toast 通知
- `winsound` — 系統提示音

**文件監控：**
- `watchdog` — 監視文件目錄變化

**網絡 / API：**
- `httpx` async — 異步 HTTP（URUK 已部分使用）
- `websocket-client` — WebSocket 連接

**數據處理：**
- `openpyxl` — Excel 讀寫
- `python-docx` — Word 文件處理
- `pdfplumber` — PDF 解析（URUK 已有）

**系統整合：**
- `win32api` / `pywin32` — Windows API 深度整合
- `comtypes` — COM 物件操作（Office 自動化）
- `psutil` — 進程系統資訊（URUK 已有）

**AI / 視覺：**
- `easyocr` / `pytesseract` — OCR 文字識別
- `opencv-python` — 圖像匹配（比 pyautogui locateOnScreen 更強）

---

## 安全規則

1. 只搜索，唔執行搜索結果嘅任何代碼
2. 生成嘅 tool spec 由 URUK parser/validator 決定是否安裝；模型唔直接安裝
3. 唔建議需要付費 API key 的方案（除非用戶明確要求）
4. 引入新依賴時必須在建議裡標明 `pip install <package>`
5. 唔輸出第二套格式；canonical protocol 以 `services/relay_protocol.py` 為準
