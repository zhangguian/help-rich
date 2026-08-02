# AI 问一问"没发现要查什么股票"修复

## 根因

作用域链路完整(前端 stockCode/stockName → build_question_system 系统提示词),但 **user prompt 数据块缺股票标识**:
- `_build_question_prompt`(stock_advice_service.py:229)的 `ctx` 是 `_build_context` 纯数字 JSON(指标 + recent_klines),无代码、无名称
- 模型只在 system 见过 "贵州茅台(600519)",user 侧"该股指标:{纯数字}"无绑定 → 轻量模型答"没发现要查什么股票"

## 1. 后端修复 `backend/app/services/stock_advice_service.py`

- `_build_question_prompt` 加参数 `stock_code: str | None = None, stock_name: str | None = None`:
  - prompt 开头加标识行:`股票: 贵州茅台(600519.SH)`(无名退化为 `股票: 600519.SH`)
  - `ctx` JSON 内嵌 `"stock_code"` / `"stock_name"` 字段(绑定数字块与股票)
- `ask_stock_question` / `ask_stock_question_stream` 调用处传 `stock_code, stock_name`

## 2. 测试 `backend/tests/test_stock_advice.py`

- 更新 `test_prompt_injects_sector`:传 `"600519.SH", "贵州茅台"`,断言 `股票: 贵州茅台(600519.SH)` 与 `"stock_code"` 在 prompt
- 更新 `test_prompt_no_sector_ok`:传 `"600519.SH"`,断言 `股票: 600519.SH`
- (可选)新增无名称退化断言

## 3. 验证

- `backend/.venv\Scripts\python.exe -m pytest` 全绿
- 手动:AI 问一问提问,确认不再回复"没发现要查什么股票"
