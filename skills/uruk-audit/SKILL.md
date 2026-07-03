---
name: uruk-audit
description: |
  URUK 系統缺陷審計技能（for Claude Desktop / Cowork）。
  當收到 [UPGRADE_AUDIT] 標記時觸發——主動讀取 URUK 系統文件、分析缺口、
  生成符合 URUK canonical protocol 嘅升級設計。URUK 自己解析、驗證、安裝。

  觸發條件（任一）：
  - 訊息包含 [UPGRADE_AUDIT]
  - 用戶說「審計 URUK」「分析 URUK 缺陷」「URUK 有咩問題」「掃描系統」
  - 用戶說 audit uruk / uruk audit / uruk gap analysis

  唔同於 uruk-self-upgrade：呢個 skill 係主動分析員，自己讀文件做判斷，
  唔係等別人發格式化建議過嚟。
---

# URUK Audit Skill — 系統缺陷審計

## 用途

主動讀取 URUK 系統嘅真實狀態，識別工具缺口、可靠性問題、對話失敗模式，
輸出有依據嘅升級建議。

## 執行流程

### 步驟一：讀取系統狀態

用 Read 工具讀取以下文件：

**工具清單（必讀）：**
```
C:\uruk-trinity-console\services\computer_tools.py
```
從中提取所有 `name=` 字段，建立現有工具列表。

**自定義工具目錄：**
```
C:\uruk-trinity-console\services\custom_tools\
```
列出已安裝嘅自定義工具。

**升級日誌：**
```
C:\uruk-trinity-console\data\upgrade_log.jsonl
```
了解已做過嘅升級，避免重複建議。

**最近 session（讀最新 5-10 個）：**
```
C:\uruk-trinity-console\data\sessions\
```
用 Glob 找最新嘅 `.json` 文件，讀取 `input`、`council`、`error` 欄位。

**Planner 規則（了解現有限制）：**
```
C:\uruk-trinity-console\planner_executor.py
```
讀取 `PLANNER_SYSTEM_PROMPT` 部分，了解 Planner 現有嘅規則同限制。

### 步驟二：分析缺口

根據讀取嘅數據，分析以下維度：

**工具缺口分析：**
- 用戶嘗試做但系統唔識做嘅操作（session 入面 error 或「唔支援」類型嘅 council 回覆）
- 工具類別唔平衡（某個類別工具太少）
- 明顯缺少但常用嘅操作（例如：截取特定視窗、讀取 Excel、發送通知等）

**可靠性問題分析：**
- 邊類操作失敗率高
- Planner 規則有冇明顯缺漏（例如：冇處理某類 UI 恢復 session 問題）

**升級歷史分析：**
- 最近裝咗咩工具
- 有冇重複嘅需求模式

### 步驟三：生成 canonical upgrade output

收到 URUK 發送嘅訊息中會包含計劃書 ID（格式：`[UPGRADE_PLAN:upgrade-YYYYMMDD-HHMMSS-xxxxxx]`）。
必須先輸出 `[UPGRADE_EXECUTION_PLAN:<plan_id>]`，再輸出每個 `[TOOL_SPEC:<plan_id>]`，
讓 URUK 自動解析、驗證、安裝、hot reload、smoke test、寫 log。

選出最有價值嘅 **最多 3 個** 升級建議。

每個建議必須：
- 有具體依據（引用讀到嘅 session 或錯誤模式）
- 唔與現有工具重複
- 技術可行（Python 可以實現）

輸出格式（plan_id 從訊息頭部的 [UPGRADE_PLAN:xxx] 提取）：
```
[AUDIT_FINDINGS]
分析摘要：<2-3 句話總結>
主要缺口：<列表>

[UPGRADE_EXECUTION_PLAN:<plan_id>]
{
  "tool_rules": {
    "executor_role": "local small model confirms validate/install/reload/test/log; URUK deterministic code executes",
    "global_allowed_actions": ["validate_code", "install_tools", "hot_reload", "smoke_test", "write_log"],
    "safety_rules": ["do not install failed validation tools", "requires_human=true for dangerous code"],
    "stop_conditions": ["all validation failed", "human confirmation required"]
  },
  "steps": [
    {"action": "validate_code", "executor_rule": "confirm specs can be statically validated", "allowed_actions": ["validate_code"], "success_criteria": "at least one safe spec passes"},
    {"action": "install_tools", "executor_rule": "install only passed specs", "allowed_actions": ["install_tools"], "success_criteria": "custom_tools modules are written"},
    {"action": "hot_reload", "executor_rule": "reload only custom_tools registry", "allowed_actions": ["hot_reload"], "success_criteria": "new tools appear in registry"},
    {"action": "smoke_test", "executor_rule": "smoke-test only newly installed tools", "allowed_actions": ["smoke_test"], "success_criteria": "passed/failed list returned"},
    {"action": "write_log", "executor_rule": "write audit log for installed tools only", "allowed_actions": ["write_log"], "success_criteria": "upgrade log records plan id"}
  ]
}

[TOOL_SPEC:<plan_id>]
name: <snake_case 工具名>
description: <廣東話描述>
category: <類別>
args:
  - name: <arg>
    type: str
    required: true
    description: <用途>
python_code: |
  def execute(args: dict) -> dict:
      try:
          # 實現
          return {"result": ...}
      except Exception as e:
          return {"error": str(e)}
---

[TOOL_SPEC:<plan_id>]
... (第二個工具)
---
```

⚠ 每個 [TOOL_SPEC] 區塊必須以 `---` 結束，URUK 才能正確解析邊界。

### 步驟四：交由 URUK 執行

模型到此為止。唔好直接寫檔、唔好執行 shell、唔好 hot reload。
URUK `upgrade_engine.py` 負責：解析 → 驗證 → 寫入 → 熱載入 → smoke test → 審計日誌 → loop health check。

---

## 分析參考：常見缺口模式

以下係喺 URUK 系統常見但容易缺少嘅能力，作為分析參考：

**視窗管理類：**
- 等待特定視窗出現（有 timeout 嘅 wait_for_window）
- 截取特定視窗嘅截圖（唔係全屏）
- 最大化 / 最小化視窗

**輸入類：**
- 安全清空輸入欄再輸入（唔靠座標）
- 按 Tab 鍵跳轉欄位

**文件類：**
- 讀取 Excel/CSV 並返回結構化數據
- 監視文件變化（file watcher）
- 批量重命名文件

**網絡類：**
- 帶 header / cookie 嘅 HTTP 請求
- 解析 JSON API 返回

**系統通知類：**
- 發送 Windows toast 通知
- 播放系統提示音

---

## 安全規則

同 uruk-self-upgrade 一致：
1. 分析只讀文件，唔修改任何系統文件
2. 生成嘅建議由 URUK parser/validator 決定是否安裝；模型唔直接安裝
3. 唔建議會覆蓋現有核心工具嘅方案
4. 唔輸出第二套格式；canonical protocol 以 `services/relay_protocol.py` 為準
