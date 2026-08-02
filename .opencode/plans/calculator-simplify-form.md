# 成本计算器表单简化:仅点选 + 股数/成本价

用户确认:股票代码**仅点选持仓列表**(移除手动输入框);**保留买入/卖出方向选择**;表单只需填 **股数 + 成本价**。

## 修改 `frontend/src/components/calculator/CalculatorPanel.tsx`

### 1. 移除股票代码输入框
- 删除"预交易"卡片顶部的 `<input>` 代码框
- `stockCode` 保留(由 initialCode / 持仓行点击设置),但不再有手动编辑入口

### 2. "预交易"卡片顶部显示当前选中股票
- 加展示行:`豫能控股 001896.SZ`(名称 + 代码 font-mono text-xs),让用户知道当前计算对象
- `currentPosition?.stockName ?? stockCode` 显示

### 3. 价格框 label 改名"成本价"
- 原 `价格` label → `成本价`(与用户表述一致;placeholder `11.000` 保留)

### 4. 无持仓场景
- 左侧"暂无持仓"时,右侧表单区替换为提示 `暂无持仓,无法选择股票`(表单不可用,避免悬空默认代码)
- 表单区改为条件渲染:有 positions 且 >0 时显示表单;否则提示

### 5. 不动项
- 股数/成本价输入、买卖 radio、300ms 自动计算、21 档热力图、持仓列表三态(加载/错误重试/列表)、initialCode 默认选中

## 修改 `frontend/src/app/page.tsx`
- 无需改动(已传 `initialCode={activeCode}`)

## 兼容性
- settings 页入口(无 initialCode):无持仓时显示提示;有持仓时默认选中第一只?不——settings 入口无选中股,stockCode 初始 `'000001.SZ'`,列表无高亮。改进:settings 场景默认不高亮,用户点选后生效。维持现有初始值即可(行高亮 = normalizeCode(stockCode) 匹配才有,000001 无持仓则无高亮,点选后高亮)

## 验证
- `cd frontend && npm run build`
- 手动:工作台选中持仓股 → 弹窗默认选中该股(顶部显示名称代码);点列表切换联动;只填股数+成本价即出结果;settings 入口无持仓时提示
