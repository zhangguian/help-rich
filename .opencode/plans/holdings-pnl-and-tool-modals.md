# 持仓盈亏显示在中间行情条 + Tab 结构 + 计算器/持仓体检弹窗化

用户需求(已确认):
- **盈亏显示在中间部分(选中股票的行情条 section)**,不是左侧列表行
- 自选 tab 与持仓 tab **保持分开**(现状已满足),自选列表**自动包含持仓股**(现状已满足)→ 无需改动
- 计算器、持仓体检页用弹窗显示,删除原路由页

## 1. 中间行情条显示持仓盈亏(红涨绿跌)

`frontend/src/app/page.tsx`:
- 从 `positions` 找选中股持仓:`const activePosition = positions.find((p) => p.stockCode === activeCode)`
- 中间行情条 GlassCard(约 235-255 行)改动:
  - **修复"已持仓"徽标**:现用 `selectedQuote?.name ? '已持仓' : ''`(误判),改为 `activePosition != null`
  - 右侧现价/涨幅下方追加盈亏行(仅 `activePosition` 存在时渲染,红涨绿跌 text-xs):
    - 今日盈亏:`今日 +¥5.20`
    - 浮盈:`浮盈 +¥123.45 (+12.3%)`
  - 数据:`todayPnl` / `floatingPnl` 直接 Number();`ratioPct = Number(totalCost) > 0 && floatingPnl != null ? floatingPnl / Number(totalCost) * 100 : null`
  - 未持仓股不显示盈亏行;非持仓 tab(板块/快讯)不受影响
- `WatchList.tsx` / `WatchItem`:**不加**盈亏字段(撤销旧方案,保持原样)

## 2. Tab 结构(确认现状,不改)

- 自选 tab:`watchAll` = 自选 ∪ 持仓(持仓股默认进自选,`inPosition` 徽标保留)
- 持仓 tab:`visibleItems` = 仅 `positions`
- 两 tab 独立,符合要求

## 3. 弹窗化

- `frontend/src/components/ui/LiquidModal.tsx`:size 联合类型加 `'xl'`,widths 加 `xl: 'max-w-4xl'`(计算器左右分栏 + 21 列热力图,lg 672px 太挤)
- 新建 `frontend/src/components/holdings-health/HoldingsHealthPanel.tsx`:
  - `src/app/holdings-health/page.tsx` 主体(STATUS_LABEL + 数据加载 + 总览 4 卡 + 风险提示 + 单只列表)整体移入,去掉页面 header
- 计算器:直接复用 `components/calculator/CalculatorPanel.tsx`(已组件化、自拉数据)
- 新建 `frontend/src/components/settings/HistoryToolsCard.tsx`('use client'):
  - 原 settings 页 "🕰 历史工具" Card(标题 + 说明 + 2 列 8 按钮网格)
  - 计算器(弹窗 xl) / 持仓健康(弹窗 lg):按钮 → LiquidModal
  - 其余 6 个(流水/年账单/风险报告/调仓建议/Provider 占比/板块资金流)保持 Link
  - 弹窗内容可滚动(max-h-[90vh] overflow-y-auto 已有)
- `frontend/src/app/settings/page.tsx`:41-89 行 Card 区块替换为 `<HistoryToolsCard />`,清理多余 import

## 4. 删除路由页

- 删除 `frontend/src/app/holdings-health/page.tsx`、`frontend/src/app/calculator/page.tsx`
- grep 确认无残留引用

## 5. 验证

- `cd frontend && npm run build`
- 手动:选中持仓股 → 中间行情条显示今日/浮盈/盈亏率且红涨绿跌;未持仓股无盈亏行;自选/持仓 tab 列表正确;设置页两弹窗打开/关闭/滚动正常
