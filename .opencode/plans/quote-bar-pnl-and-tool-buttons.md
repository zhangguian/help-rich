# 中间行情条布局修改:盈亏移名称下 + 计算器/持仓分析入口

用户需求(工作台中间选中股票行情条 GlassCard):
1. 今日盈亏 / 总盈亏(浮盈)**移到股票名称下方,水平排列**(当前在右侧数字区竖排)
2. 新增 **成本计算器** 与 **持仓分析** 两个入口按钮(点击弹窗,复用已弹窗化的 CalculatorPanel / HoldingsHealthPanel)

## 修改 `frontend/src/app/page.tsx`(纯前端)

### 1. 行情条左列(名称/代码/徽标下方)加水平盈亏行
- 用现有 `positionPnl`(todayPnl / floatingPnl / ratioPct)
- `flex gap-2 text-xs font-mono`,两段:
  - `今日 +¥54.00`(红涨绿跌,pctClass)
  - `浮盈 -¥1944.00 (-35.03%)`(红涨绿跌)
- 无持仓股不渲染此行

### 2. 行情条右列删除原盈亏竖排块(271-290 行)
- 保留现价 + 涨幅

### 3. 右列涨幅下方加按钮行
- `flex justify-end gap-2 mt-2`,两个 `Button size="sm" variant="secondary"`:
  - `🧮 成本计算器` → `setShowCalc(true)`
  - `🩺 持仓分析` → `setShowHealth(true)`
- 文案按用户原话:"成本计算器" / "持仓分析"(持仓分析 = 持仓体检面板 HoldingsHealthPanel)

### 4. 弹窗状态与渲染
- `useState`:`showCalc` / `showHealth`(默认 false)
- main 顶层渲染两个 `LiquidModal`(无条件挂载,open 控制):
  - `🧮 成本计算器` size `xl` → `<CalculatorPanel />`
  - `🩺 持仓分析` size `lg` → `<HoldingsHealthPanel />`
- import 新增:Button / LiquidModal / CalculatorPanel / HoldingsHealthPanel

## 验证
- `cd frontend && npm run build`
- 手动:选中持仓股 → 名称下水平盈亏(红涨绿跌);两个按钮打开对应弹窗;未持仓股无盈亏行
