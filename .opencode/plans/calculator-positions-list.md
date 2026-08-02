# 计算器弹窗:持仓列表 + 默认选中当前股票

## 现象与根因
- 现象:左侧选中持仓股 → 点"成本计算器" → 弹窗显示"无此股票持仓(空仓建仓)"
- 根因:CalculatorPanel 左侧"当前持仓"卡片只显示**输入框代码匹配的单只持仓**;输入框默认 `'000001'`,与当前选中股无关 → 未匹配 → 空仓提示
- 次因:持仓拉取失败被 `.catch(() => {})` 静默吞掉(无提示/无重试)

## 用户期望
1. 弹窗打开时**默认选中当前左侧选中的股票**(输入框同步为该股,显示其持仓)
2. 左侧改为**完整持仓列表**,点选任一持仓自动填入输入框并实时计算

## 修改 `frontend/src/components/calculator/CalculatorPanel.tsx`

### 1. 新增 prop `initialCode`
- `export function CalculatorPanel({ initialCode = null }: { initialCode?: string | null })`
- `stockCode` 初始值:`initialCode ? normalizeCode(initialCode) ?? '000001' : '000001'`
- `useEffect` 监听 `initialCode` 变化同步:`setStockCode(normalizeCode(initialCode) ?? ...)`
  (弹窗常驻挂载,再次打开时 activeCode 已变,需同步;settings 页入口无 initialCode,行为不变)

### 2. 左侧卡片改为完整持仓列表
- 结构:`当前持仓` → 状态三分支:
  - **加载失败**:`⚠ 持仓加载失败 + [重试]` 按钮(不再静默,`positionsError` state)
  - **无持仓**:`暂无持仓(空仓建仓)`
  - **有列表**:`ul max-h-64 overflow-y-auto space-y-1`,每行一个按钮:
    - 名称 + 代码(`font-mono text-xs`)、次行 `股数 · 成本 ¥x · 浮盈 +¥x`(红涨绿跌,浮盈 null 显示 '--')
    - 当前选中行高亮(`bg-accent-subtle border border-accent/25` 同现有选中样式),点击 → `setStockCode(p.stockCode)`
- 数据:现有 `positions` state(拉取逻辑保留,仅 catch 加错误态 + `loadPositions` 可重试)

### 3. 拉取逻辑
- `loadPositions` useCallback:setLoading → apiGet('/positions') → 成功 setPositions / 失败 setPositionsError
- 挂载 useEffect 调一次;`[重试]` 按钮再次调用

## 修改 `frontend/src/app/page.tsx`
- 成本计算器弹窗:`<CalculatorPanel initialCode={activeCode} />`(将当前选中股传入)

## 兼容性
- settings 页 `HistoryToolsCard` 的 CalculatorPanel 无 prop → 默认 `'000001'`,行为不变
- 后端零改动;现有实时计算逻辑(输入即算/21 档)不动

## 验证
- `cd frontend && npm run build`
- 手动:左侧选中持仓股 → 计算器弹窗默认选中该股并显示其持仓;点列表其他持仓 → 输入框联动实时计算;停后端验证错误态与重试
