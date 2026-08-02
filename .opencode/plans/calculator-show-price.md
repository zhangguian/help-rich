# 计算器持仓列表:补充现价显示

## 现状
持仓行次行:`{shares} 股 · 成本 ¥{avgCost}` + 右对齐浮盈——**缺当前股价**,且成本与浮盈挤在一起不明显。

## 修改 `frontend/src/components/calculator/CalculatorPanel.tsx`(持仓列表行,约 168-176 行)

### 1. 次行加现价
- `{shares} 股 · 成本 ¥{p.avgCost} · 现价 ¥{p.currentPrice ?? '--'}`
- `Position.currentPrice` 为 `string | null`,行情不可用时显示 `--`

### 2. 现价红涨绿跌
- 用 `currentPrice` vs `prevClose` 判定:
  - 两者均非 null 且不等:`现价 > 昨收` → `text-up`(红)/ 反之 `text-down`(绿)
  - 任一 null → `text-text-sec`(中性)
- 与全局红涨绿跌规范一致

### 3. 浮盈保留
- 右对齐 `+¥54.00`(红涨绿跌)不动

## 布局
- 保持现有两行结构(名称/代码行 + 信息行),信息行左段变长,浮盈右对齐;若实际拥挤再评估换行
- 弹窗 xl 宽度下左卡片空间充足

## 验证
- `cd frontend && npm run build`
- 手动:打开计算器,持仓行显示 股数/成本/现价(红绿) + 浮盈;停行情(后端断网)验证 `--` 降级
