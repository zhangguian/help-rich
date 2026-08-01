# 前端架构文档:盘后诊股室

**文档版本**:v1.3
**创建日期**:2026-07-31
**最后更新**:2026-07-31(v1.3 补齐 P2 盲点:暗色图表适配 / TypeScript 严格性,修正 Decimal→string 类型)
**文档状态**:已通过实战评审,准备实施
**目标读者**:前端开发者(自用项目,实际就是用户本人)
**配套文档**:
- `backend-architecture.md`(后端架构,API 契约权威)
- `project-book.md`(PM 项目书,Source of Truth)
- `ui-ux-design.md`(UI/UX 设计书,组件与样式权威)

---

## 第 1 章 总体定位

### 1.1 核心职责

盘后诊股室前端负责:
- **用户界面**:5 个核心页面(首页/计算器/流水/设置/年度账单)
- **交互逻辑**:录入表单、实时计算、评分展示
- **数据展示**:21 档热力图、K 线图、评分详情、年度账单
- **SSE 订阅**:接收诊断评分与 AI 评语
- **定时轮询**:止损提醒、价格刷新
- **本地状态**:主题偏好、止损设置、表单草稿

### 1.2 进程模型

```
本机启动两个进程:
- frontend:Next.js :5173(开发模式)
- backend:uvicorn :8000(API)

启动顺序:先 backend,后 frontend
访问:浏览器打开 http://localhost:5173
```

### 1.3 与后端的关系

| 维度 | 前端职责 | 后端职责 |
|---|---|---|
| API 调用 | 发起请求 + 展示结果 | 定义契约 + 处理逻辑 |
| 类型 | 从 OpenAPI 生成 TS 类型 | Pydantic schemas(权威) |
| SSE 订阅 | EventSource 客户端 | 事件发布 |
| 错误处理 | 展示错误码 + Toast | 定义错误码 |
| 业务逻辑 | UI 交互(无核心逻辑) | 评分算法(纯函数) |
| **数据源** | 只消费 `UnifiedQuote` 格式 | `data-source-guide.md` 定义,后端抽象 |

---

## 第 2 章 技术栈

| 项 | 技术 | 版本 |
|---|---|---|
| 框架 | Next.js | 14.x(App Router) |
| UI 库 | React | 18.x |
| 类型 | TypeScript | 5.x |
| 样式 | Tailwind CSS | 3.x |
| 基础组件 | @radix-ui/* | 最新 |
| 行为组件 | @headlessui/react | 最新 |
| 表格 | @tanstack/react-table | 最新 |
| 表单 | react-hook-form | 最新 |
| 校验 | zod | 最新 |
| 状态 | zustand | 最新 |
| 图表 | echarts + echarts-for-react | 5.x |
| 图标 | lucide-react | 最新 |
| class 合并 | clsx + tailwind-merge | 最新 |
| 动效 | framer-motion | 最新 |
| 主题 | next-themes | 最新 |
| 类型生成 | openapi-typescript | 最新 |
| 测试 | vitest + @testing-library/react | 最新 |

---

## 第 3 章 目录结构

```
frontend/
├── src/
│   ├── app/                       # Next.js App Router
│   │   ├── layout.tsx             # 全局布局(主题、导航)
│   │   ├── page.tsx               # 首页(持仓概览)
│   │   ├── transactions/
│   │   │   └── page.tsx           # 流水录入
│   │   ├── calculator/
│   │   │   └── page.tsx           # 成本计算器
│   │   ├── settings/
│   │   │   └── page.tsx           # 设置
│   │   ├── annual-report/
│   │   │   └── [year]/
│   │   │       └── page.tsx       # 年度账单详细页(可选)
│   │   └── globals.css            # 全局样式 + CSS 变量
│   ├── components/
│   │   ├── ui/                    # 基础组件
│   │   │   ├── Button.tsx
│   │   │   ├── Input.tsx
│   │   │   ├── Select.tsx
│   │   │   ├── Card.tsx
│   │   │   ├── Modal.tsx
│   │   │   ├── Toast.tsx
│   │   │   ├── Badge.tsx
│   │   │   └── Skeleton.tsx
│   │   ├── charts/                # 图表组件
│   │   │   ├── KLineChart.tsx
│   │   │   ├── PnlHeatmap.tsx     # 21 档 SVG
│   │   │   └── MiniSparkline.tsx
│   │   ├── transaction/           # 流水相关
│   │   │   ├── TransactionForm.tsx
│   │   │   ├── TransactionTable.tsx
│   │   │   └── TransactionRow.tsx
│   │   ├── calculator/
│   │   │   ├── CalculatorPanel.tsx
│   │   │   ├── PositionPanel.tsx
│   │   │   └── PnlGrid.tsx
│   │   ├── signal/                # 评分相关
│   │   │   ├── ScoreBadge.tsx
│   │   │   ├── ScoreDetail.tsx
│   │   │   └── ScoreBreakdown.tsx
│   │   ├── stop-loss/             # 止损(v1.5)
│   │   │   ├── StopLossModal.tsx
│   │   │   ├── StopLossAlert.tsx
│   │   │   └── StopLossButton.tsx
│   │   ├── annual-report/         # 年度账单(v1.5)
│   │   │   └── AnnualReportCard.tsx
│   │   └── layout/
│   │       ├── Navigation.tsx
│   │       ├── ThemeToggle.tsx
│   │       └── ComplianceFooter.tsx
│   ├── hooks/
│   │   ├── useSSE.ts              # SSE 订阅
│   │   ├── useStopLossChecker.ts  # 止损定时轮询
│   │   ├── useMarketHours.ts      # 交易时段判断
│   │   ├── useQuoteRefresh.ts     # 价格刷新
│   │   └── useDebounce.ts         # 输入防抖
│   ├── stores/                    # Zustand
│   │   ├── usePortfolioStore.ts
│   │   ├── useTransactionStore.ts
│   │   ├── useStopLossStore.ts
│   │   └── useUIStore.ts          # 主题 / 侧边栏 / Toast
│   ├── lib/
│   │   ├── api.ts                 # axios 实例
│   │   ├── eventSource.ts         # SSE 客户端封装
│   │   ├── decimalFormat.ts       # 数字格式化
│   │   ├── notification.ts        # Web Notification + 振动
│   │   └── types.ts               # API 类型(从 OpenAPI 生成)
│   ├── styles/
│   │   └── tokens.css             # 设计 tokens(色板/字号/间距)
│   └── public/
├── tailwind.config.ts             # 设计 tokens 映射
├── tsconfig.json
├── next.config.ts
└── package.json
```

---

## 第 4 章 路由策略

### 4.1 App Router 结构

| 路由 | 页面 | 渲染策略 |
|---|---|---|
| `/` | 首页(持仓概览) | Client |
| `/transactions` | 流水录入 | Client |
| `/calculator` | 成本计算器 | Client |
| `/settings` | 设置 | Client |
| `/annual-report/[year]` | 年度账单详细页 | Client |

### 4.2 MVP 全部 Client Components 的原因

- **数据频繁更新**:价格、评分、止损触发,客户端实时性更强
- **用户交互密集**:表单、弹窗、轮询,需要客户端状态
- **本地状态重要**:止损设置、主题、表单草稿
- **MVP 简化**:不引入 SSR 数据获取层,降低开发复杂度

### 4.3 何时用 Server Components(v0.2+)

- 静态页(年度账单报告页,可 SSG)
- SEO 优化(本项目不需要)

---

## 第 5 章 组件分层

### 5.1 三层结构

```
ui/              基础组件(纯展示,无业务)
  ↓
business/        业务组件(含业务逻辑,知道数据含义)
  ↓
pages/           页面组件(数据获取 + 状态 + 组装)
```

### 5.2 组件粒度原则

| 类型 | 粒度 | 例子 |
|---|---|---|
| 基础组件 | 单功能,可复用 | Button、Input、Card |
| 业务组件 | 含业务语义 | ScoreBadge、TransactionForm |
| 页面组件 | 单页面,组合 | HomePage、CalculatorPage |

### 5.3 复用边界

- 业务组件**不**调用 API(由页面组件调用 + 传 props)
- 业务组件**不**访问 Zustand store(由页面组件订阅 + 传 props)
- 例外:`useUIStore`(主题、Toast)可在所有组件访问

---

## 第 6 章 状态管理(Zustand)

### 6.1 Store 划分

| Store | 内容 | 触发更新 |
|---|---|---|
| `usePortfolioStore` | 持仓列表 | API 拉取 / 轮询 |
| `useTransactionStore` | 流水列表 + 评分 | API 拉取 / SSE 推送 |
| `useStopLossStore` | 止损设置 + 触发状态 | API 拉取 / 定时轮询 |
| `useUIStore` | 主题 / 侧边栏 / Toast | 用户操作 |

### 6.2 典型 Store

```typescript
// stores/usePortfolioStore.ts
import { create } from 'zustand';
import type { Position } from '@/lib/types';

interface PortfolioState {
  positions: Position[];
  loading: boolean;
  fetchPositions: () => Promise<void>;
}

export const usePortfolioStore = create<PortfolioState>((set) => ({
  positions: [],
  loading: false,
  fetchPositions: async () => {
    set({ loading: true });
    const res = await api.get<Position[]>('/positions');
    set({ positions: res.data, loading: false });
  },
}));
```

### 6.3 状态流向

```
API 拉取 → Store → 组件订阅
SSE 推送 → Store(直接更新) → 组件重渲染
用户操作 → 组件 → Store(action) → API 调用
```

### 6.4 持仓聚合:派生数据模式(v1.2 新增)

**问题**:如果 `usePortfolioStore` 独立存储持仓,需要手动同步 "流水变化 → 持仓变化",容易出错。

**解决方案**:**持仓从流水派生**,不独立存储。

```typescript
// stores/useTransactionStore.ts
interface TransactionStore {
  transactions: Transaction[];
  fetchTransactions: () => Promise<void>;
  // 不存储持仓
}

// 派生:持仓 = 流水聚合
export function useDerivedPortfolio() {
  const transactions = useTransactionStore((s) => s.transactions);
  
  // useMemo 缓存,只依赖 transactions 变化
  const positions = useMemo(() => {
    return aggregatePositions(transactions);
  }, [transactions]);
  
  return positions;
}

// 聚合函数(纯函数)
function aggregatePositions(transactions: Transaction[]): Position[] {
  const map = new Map<string, Position>();
  for (const tx of transactions) {
    const existing = map.get(tx.stockCode) || {
      stockCode: tx.stockCode,
      stockName: tx.stockName,
      shares: 0,
      totalCost: 0,
    };
    if (tx.action === 'buy') {
      existing.shares += tx.shares;
      existing.totalCost += tx.shares * tx.price;
    } else {
      // 卖出:先进先出
      existing.shares -= tx.shares;
      existing.totalCost -= tx.shares * existing.avgCost;
    }
    existing.avgCost = existing.shares > 0 ? existing.totalCost / existing.shares : 0;
    map.set(tx.stockCode, existing);
  }
  return Array.from(map.values()).filter(p => p.shares > 0);
}
```

**优势**:
- 单一数据源(transactions),不会不一致
- 录入交易后,持仓自动更新
- 派生数据缓存(useMemo),性能 OK

### 6.5 持久化

- 主题:`next-themes` 自动持久化到 localStorage
- 止损设置:**不需要前端持久化**(后端 SQLite 存储)
- 表单草稿:可选,MVP 不做

---

## 第 7 章 数据获取

### 7.1 axios 实例(v1.1 加 snake_case → camelCase 自动转换)

**命名约定**:后端 Pydantic 用 snake_case(`stock_code`, `tx_shares`),前端 TS 用 camelCase(`stockCode`, `txShares`)。在 axios 拦截器中自动转换。

```typescript
// lib/api.ts
import axios from 'axios';
import { useUIStore } from '@/stores/useUIStore';

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  timeout: 10000,
});

// 响应拦截器:snake_case → camelCase + 统一错误处理
api.interceptors.response.use(
  (response) => {
    response.data = snakeToCamel(response.data);
    return response;
  },
  (error) => {
    if (error.response?.data?.code) {
      const { code, message } = error.response.data;
      useUIStore.getState().showToast({ type: 'error', message });
    }
    return Promise.reject(error);
  }
);

// snake_case → camelCase 转换工具
function snakeToCamel(obj: any): any {
  if (Array.isArray(obj)) return obj.map(snakeToCamel);
  if (obj !== null && typeof obj === 'object' && !(obj instanceof Date)) {
    return Object.fromEntries(
      Object.entries(obj).map(([k, v]) => [
        k.replace(/_([a-z])/g, (_, c) => c.toUpperCase()),
        snakeToCamel(v),
      ])
    );
  }
  return obj;
}
```

**效果**:后端返回 `{ stock_code: "000001", tx_shares: 500 }`,前端代码可直接用 `transaction.stockCode`、`transaction.txShares`。

### 7.2 数据获取模式

```typescript
// 页面组件中
const { positions, loading, fetchPositions } = usePortfolioStore();

useEffect(() => {
  fetchPositions();
}, []);

if (loading) return <Skeleton />;
return <StockQuoteCardList positions={positions} />;
```

### 7.3 缓存策略

- **客户端缓存**:Zustand store 自然持久(页面不卸载就不丢)
- **HTTP 缓存**:MVP 不引入(数据频繁更新)
- **手动刷新**:用户在持仓页点 [↻ 刷新行情] 强制拉取

---

## 第 8 章 SSE 集成

### 8.1 EventSource 客户端(v1.1 加心跳处理 + 降级持久化)

**心跳**:后端每 30s 推 `{ event: 'ping' }`,前端过滤掉不处理。

**降级状态持久化**:localStorage 记录"已降级到轮询"标志,刷新页面后保留。

```typescript
// lib/eventSource.ts
const DEGRADED_KEY = 'rich:sse_degraded';

export class EventSourceClient {
  private url: string;
  private es: EventSource | null = null;
  private reconnectAttempts = 0;
  private degraded = localStorage.getItem(DEGRADED_KEY) === '1';

  constructor(url: string, onMessage: (data: any) => void) {
    this.url = url;
    if (this.degraded) {
      // 持久化降级状态,跳过 SSE 直接轮询
      this.startPolling(onMessage);
    } else {
      this.connect(onMessage);
    }
  }

  connect(onMessage: (data: any) => void) {
    this.es = new EventSource(`${this.url}?client_id=${Date.now()}`);
    this.es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        if (event.event === 'ping') return;  // 忽略心跳
        onMessage(event);
      } catch (err) {
        console.error('SSE parse error', err);
      }
    };
    this.es.onerror = () => {
      this.es?.close();
      this.reconnectAttempts++;
      // 失败 3 次后降级到轮询
      if (this.reconnectAttempts >= 3) {
        localStorage.setItem(DEGRADED_KEY, '1');
        this.startPolling(onMessage);
        return;
      }
      // 指数退避重连
      const delay = Math.min(3000 * Math.pow(2, this.reconnectAttempts - 1), 30000);
      setTimeout(() => this.connect(onMessage), delay);
    };
  }

  startPolling(onMessage: (data: any) => void) {
    // 降级模式:每 5 秒轮询
    const interval = setInterval(async () => {
      try {
        const res = await api.get('/diagnose/pending');
        res.data.forEach((event: any) => onMessage(event));
      } catch (err) {
        console.error('Polling failed', err);
      }
    }, 5000);
    // 保存 interval 以便清理
    (this as any)._pollingInterval = interval;
  }

  close() {
    this.es?.close();
    if ((this as any)._pollingInterval) {
      clearInterval((this as any)._pollingInterval);
    }
  }
}
```

**网络恢复时回切**:监听 `online` 事件,清除降级标记,重连 SSE。

```typescript
// 在 RootLayout 中
useEffect(() => {
  const handleOnline = () => {
    localStorage.removeItem(DEGRADED_KEY);
    // 触发页面刷新或主动重连
  };
  window.addEventListener('online', handleOnline);
  return () => window.removeEventListener('online', handleOnline);
}, []);
```

### 8.2 useSSE Hook

```typescript
// hooks/useSSE.ts
import { useEffect } from 'react';
import { EventSourceClient } from '@/lib/eventSource';

export function useSSE<T>(url: string, onMessage: (data: T) => void) {
  useEffect(() => {
    const client = new EventSourceClient(url, onMessage);
    return () => client.close();
  }, [url]);
}
```

### 8.3 业务事件订阅

```typescript
// 在 TransactionsPage 中
useSSE('/api/events/sse', (event) => {
  if (event.event === 'trade.scored') {
    // 更新对应行评分
    useTransactionStore.getState().updateScore(event.trade_id, event.score);
  } else if (event.event === 'trade.commented') {
    useTransactionStore.getState().updateAiComment(event.trade_id, event.comment);
  }
});
```

### 8.4 重连降级

- SSE 失败 3 次后,降级为每 5 秒轮询 `GET /api/diagnose/{trade_id}`
- 提示用户"实时连接不稳定,已切换到轮询模式"

---

## 第 9 章 主题系统

### 9.1 next-themes 集成

```typescript
// app/layout.tsx
import { ThemeProvider } from 'next-themes';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
```

### 9.2 CSS 变量切换

`styles/tokens.css`:
```css
:root {
  --bg-base: #FAFAFA;
  --bg-surface: #FFFFFF;
  --text-primary: #171717;
  --status-up: #DC2626;
  --status-down: #16A34A;
}

[data-theme="dark"] {
  --bg-base: #0A0A0A;
  --bg-surface: #141414;
  --text-primary: #FAFAFA;
  --status-up: #F87171;
  --status-down: #4ADE80;
}
```

### 9.3 主题切换按钮

```tsx
// components/layout/ThemeToggle.tsx
'use client';
import { useTheme } from 'next-themes';
import { Moon, Sun } from 'lucide-react';

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
      {theme === 'dark' ? <Sun /> : <Moon />}
    </button>
  );
}
```

### 9.4 暗色图表适配(v1.3 新增)

> **盲点**:双主题只适配了页面,图表(ECharts K 线 / 自研 SVG 21 档)没处理会在暗色下"刺眼"或"看不见"。

#### 9.4.1 ECharts(未来 K 线)双主题

```typescript
// components/charts/KLineChart.tsx
import { useTheme } from 'next-themes';

// 两套 theme 配置(registerTheme)
const lightTheme = {
  backgroundColor: 'transparent',
  textStyle: { color: '#525252' },
  axisLine: { lineStyle: { color: '#E5E5E5' } },
  splitLine: { lineStyle: { color: '#F5F5F5' } },
};
const darkTheme = {
  backgroundColor: 'transparent',
  textStyle: { color: '#A3A3A3' },
  axisLine: { lineStyle: { color: '#262626' } },
  splitLine: { lineStyle: { color: '#0F0F0F' } },
};

// theme 变化时重设 theme 并 setOption(不能只 setOption,部分配置不刷新)
useEffect(() => {
  const chart = chartRef.current.getEchartsInstance();
  chart.dispose();           // 最稳妥:销毁重建
  initChart(theme);          // 或 echarts.registerTheme + init(theme)
}, [theme]);
```

规则:
- 涨跌色直接用 CSS 变量/UI 书 8.2 的暗色值(`#F87171` / `#4ADE80`),不写死
- 轴线/网格线/文字色全部走主题配置,不写死颜色
- 主题切换:**销毁重建**(MVP 数据量小,成本可忽略;比 setOption 增量更新可靠)

#### 9.4.2 自研 SVG(21 档热力图)

自研 SVG 用 CSS 变量天然适配,只需遵守:

```tsx
// components/charts/PnlHeatmap.tsx
// 颜色一律用 CSS 变量,禁止写死 hex
<rect fill="var(--status-up)" />        {/* 亏损(红) */}
<rect fill="var(--status-down)" />      {/* 盈利(绿) */}
<line stroke="var(--border-strong)" />  {/* 当前价标线 */}
```

暗色专项处理(UI 书 8.3 落地):
- 柱底色 = `var(--bg-elevated)`,暗色下自动变深
- 文字 = `var(--text-secondary)`,等宽数字不变
- hover 放大效果不变;tooltip 背景 = `var(--bg-elevated)` + 边框 = `var(--border-default)`

#### 9.4.3 测试要求

- 两主题下对 21 档热力图 + tooltip 截图对比(手动一次)
- 检查项:柱与文字对比度、标线可见性、无"黑底黑字"

---

## 第 10 章 核心模块技术设计

### 10.1 持仓卡(含今日盈亏)

```tsx
// components/transaction/StockQuoteCard.tsx
'use client';
import { usePortfolioStore } from '@/stores/usePortfolioStore';

export function StockQuoteCard({ position }: { position: Position }) {
  const { today_pnl, today_pnl_pct, current_price, prev_close } = position;
  
  return (
    <Card>
      <div className="flex justify-between">
        <div>
          <h3>{position.stock_name} ({position.stock_code})</h3>
          <span>当前 {current_price} {today_pnl >= 0 ? '▲' : '▼'} {today_pnl_pct}%</span>
        </div>
      </div>
      <div className="grid grid-cols-3">
        <span>持仓 {position.shares} 股</span>
        <span>成本 {position.avg_cost}</span>
        <span>总成本 {position.total_cost}</span>
      </div>
      <div className="text-status-up font-mono font-bold">
        今日 {today_pnl >= 0 ? '+' : ''}{today_pnl} ({today_pnl_pct}%)
        <small>昨收 {prev_close},现价 {current_price}</small>
      </div>
      <div className="flex gap-2">
        <Button>查看成本计算</Button>
        <Button>录流水</Button>
        <StopLossButton position={position} />
      </div>
    </Card>
  );
}
```

### 10.2 计算器 + 21 档热力图

```tsx
// components/calculator/CalculatorPanel.tsx
'use client';
import { useState } from 'react';
import { api } from '@/lib/api';

export function CalculatorPanel() {
  const [stockCode, setStockCode] = useState('000001');
  const [action, setAction] = useState<'buy' | 'sell'>('buy');
  const [txShares, setTxShares] = useState(500);
  const [txPrice, setTxPrice] = useState(11.00);
  const [result, setResult] = useState<CalculatorResponse | null>(null);

  const calculate = async () => {
    const res = await api.post('/calculator', {
      stock_code: stockCode, action, tx_shares: txShares, tx_price: txPrice,
    });
    setResult(res.data);
  };

  useEffect(() => {
    // 输入即算,无需按钮
    const timer = setTimeout(calculate, 100);
    return () => clearTimeout(timer);
  }, [stockCode, action, txShares, txPrice]);

  return (
    <div className="grid grid-cols-2 gap-4">
      <PositionPanel stockCode={stockCode} />
      <InputPanel
        action={action} setAction={setAction}
        txShares={txShares} setTxShares={setTxShares}
        txPrice={txPrice} setTxPrice={setTxPrice}
      />
      {result && <ResultPanel result={result} />}
      {result && <PnlHeatmap grid={result.pnl_grid} costAfter={result.after.cost_after} />}
    </div>
  );
}
```

### 10.3 流水录入(React Hook Form + Zod)

```tsx
// components/transaction/TransactionForm.tsx
'use client';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { api } from '@/lib/api';

const schema = z.object({
  stock_code: z.string().length(6),
  action: z.enum(['buy', 'sell']),
  shares: z.number().int().positive(),
  price: z.number().positive(),
  trade_date: z.string(),
  note: z.string().optional(),
});

export function TransactionForm({ onSuccess }: { onSuccess: () => void }) {
  const { register, handleSubmit, formState: { errors } } = useForm({
    resolver: zodResolver(schema),
  });

  const onSubmit = async (data: any) => {
    await api.post('/transactions', data);
    onSuccess();
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <input {...register('stock_code')} placeholder="股票代码" />
      {errors.stock_code && <span>{errors.stock_code.message}</span>}
      {/* ... 其他字段 ... */}
      <Button type="submit">提交</Button>
    </form>
  );
}
```

### 10.4 评分弹窗(SSE 订阅)

```tsx
// components/signal/ScoreDetail.tsx
'use client';
import { useSSE } from '@/hooks/useSSE';
import { useTransactionStore } from '@/stores/useTransactionStore';

export function ScoreDetail({ tradeId }: { tradeId: number }) {
  const { score, comment, status } = useTransactionStore(
    (state) => state.scores[tradeId]
  );

  useSSE('/api/events/sse', (event) => {
    if (event.trade_id !== tradeId) return;
    if (event.event === 'trade.scored') {
      useTransactionStore.getState().setScore(tradeId, event.score);
    } else if (event.event === 'trade.commented') {
      useTransactionStore.getState().setComment(tradeId, event.comment);
    }
  });

  if (status === 'pending') return <ScoreSkeleton />;
  return (
    <Modal>
      <h2>综合评分 {score}</h2>
      <ScoreBreakdown breakdown={...} />
      {comment ? <p>{comment}</p> : <Skeleton />}
    </Modal>
  );
}
```

### 10.5 强烈止损提醒(全屏 Modal)

```tsx
// components/stop-loss/StopLossAlert.tsx
'use client';
import { useStopLossStore } from '@/stores/useStopLossStore';

export function StopLossAlert() {
  const { alertQueue, dismissAlert } = useStopLossStore();

  if (alertQueue.length === 0) return null;

  return alertQueue.map((alert) => (
    <Modal key={alert.id} fullScreen maskClosable={false}>
      <h1>⚠ 止损提醒</h1>
      <p>{alert.stock_name}({alert.stock_code}) 已触达止损价</p>
      <p>止损价:{alert.stop_loss_price} ← 当前价:{alert.current_price}</p>
      <p>触发亏损:{alert.triggered_pnl} ({alert.triggered_pct}%)</p>
      <p>过去你曾因为"再扛一下"亏损扩大</p>
      <div>
        <Button onClick={() => dismissAlert(alert.id, 'ignore')}>暂不处理</Button>
        <Button onClick={() => dismissAlert(alert.id, 'executed')}>我已止损</Button>
      </div>
    </Modal>
  ));
}
```

### 10.6 年度账单卡片

```tsx
// components/annual-report/AnnualReportCard.tsx
'use client';
import { useAnnualReport } from '@/hooks/useAnnualReport';

export function AnnualReportCard({ year }: { year: number }) {
  const { data, loading } = useAnnualReport(year);
  if (loading) return <Skeleton />;
  return (
    <Card>
      <h2>📊 你的 {year} 股票成绩单</h2>
      <div>净盈亏:{data.net_pnl} 📈</div>
      <h3>最赚 Top 3</h3>
      {data.top5_profit.slice(0, 3).map(p => (
        <div>🥇 {p.stock_name} {p.realized_pnl}</div>
      ))}
      <h3>最亏 Top 3</h3>
      {data.top5_loss.slice(0, 3).map(p => (
        <div>💔 {p.stock_name} {p.realized_pnl}</div>
      ))}
    </Card>
  );
}
```

---

## 第 11 章 定时轮询机制

### 11.1 useStopLossChecker(止损 15s 轮询)

```typescript
// hooks/useStopLossChecker.ts
import { useEffect } from 'react';
import { api } from '@/lib/api';
import { useStopLossStore } from '@/stores/useStopLossStore';
import { usePortfolioStore } from '@/stores/usePortfolioStore';

export function useStopLossChecker() {
  const stopLosses = useStopLossStore((s) => s.stopLosses);
  const triggerAlert = useStopLossStore((s) => s.triggerAlert);

  useEffect(() => {
    if (stopLosses.length === 0) return;
    
    const interval = setInterval(async () => {
      const { data: positions } = await api.get('/positions');
      
      positions.forEach((p: Position) => {
        const sl = stopLosses.find(s => s.stock_code === p.stock_code && s.enabled);
        if (sl && p.current_price <= sl.stop_loss_price) {
          const today = new Date().toISOString().split('T')[0];
          if (sl.last_triggered_at === today) return;  // 今天已触发过
          
          triggerAlert({
            stock_code: p.stock_code,
            stock_name: p.stock_name,
            stop_loss_price: sl.stop_loss_price,
            current_price: p.current_price,
            triggered_pnl: (sl.stop_loss_price - p.avg_cost) * p.shares,
            triggered_pct: (sl.stop_loss_price - p.avg_cost) / p.avg_cost,
          });
          
          // 触发通知
          if (sl.notify_sound) playAlertSound();
          if (sl.notify_desktop) showDesktopNotification(p, sl);
          if (sl.notify_vibrate) navigator.vibrate?.([200, 100, 200]);
          
          // 后端标记今日已触发
          await api.post(`/stop-losses/${p.stock_code}/triggered`);
        }
      });
    }, 15000);  // 15 秒
    
    return () => clearInterval(interval);
  }, [stopLosses]);
}
```

### 11.2 useMarketHours(交易时段)

```typescript
// hooks/useMarketHours.ts
export function useMarketHours() {
  const [scene, setScene] = useState<'morning' | 'pre-market' | 'post-market' | 'night'>(
    getCurrentScene()
  );
  
  useEffect(() => {
    const interval = setInterval(() => {
      setScene(getCurrentScene());
    }, 60000);  // 每分钟检查
    return () => clearInterval(interval);
  }, []);
  
  return scene;
}

function getCurrentScene() {
  const now = new Date();
  const hour = now.getHours();
  const minute = now.getMinutes();
  
  if (hour < 9) return 'morning';
  if (hour === 9 && minute < 30) return 'pre-market';
  if (hour < 15 || (hour === 15 && minute < 30)) return 'pre-market';
  if (hour < 22) return 'post-market';
  return 'night';
}
```

### 11.3 useQuoteRefresh(价格 5min 刷新)

```typescript
// hooks/useQuoteRefresh.ts
export function useQuoteRefresh() {
  const fetchPositions = usePortfolioStore((s) => s.fetchPositions);
  
  useEffect(() => {
    const interval = setInterval(() => {
      fetchPositions();
    }, 5 * 60 * 1000);  // 5 分钟
    return () => clearInterval(interval);
  }, []);
}
```

---

## 第 12 章 类型共享(v1.1 加 stub + 脚本)

### 12.1 双策略:stub 兜底 + openapi-typescript 生成

**问题**:openapi-typescript 需要**后端先启动**,否则前端 typecheck 失败,冷启动第一天无法开发。

**解决方案**:`src/lib/types.ts` 同时是 stub(手动)和自动生成物。

**`src/lib/types.ts`(stub 兜底,后端启动后会被覆盖)**:

```typescript
/**
 * ⚠️ 这是 stub,后端启动后请运行 `npm run gen-types` 重新生成
 * 自动生成命令:npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/types.ts
 */

export interface Transaction {
  id: number;
  stockCode: string;
  stockName: string | null;
  action: 'buy' | 'sell';
  shares: number;
  price: string;           // Decimal → string(12.5.2 规范)
  tradeDate: string;
  note: string | null;
  score: number | null;
  createdAt: string;
}

export interface Position {
  stockCode: string;
  stockName: string | null;
  shares: number;
  avgCost: string;         // Decimal → string
  totalCost: string;       // Decimal → string
  currentPrice: string | null;
  todayPnl: string | null;
  todayPnlPct: number | null;
  floatingPnl: string | null;
  floatingPnlPct: number | null;
}

export interface CalculatorResponse {
  before: { shares: number; costPrice: string; totalCost: string };
  after: { shares: number; costPrice: string | null; totalCost: string; realizedPnl: string };
  pnlGrid: Array<{ pct: number; price: string; marketValue: string; pnl: string }>;
}

export interface StopLoss {
  stockCode: string;
  stopLossPrice: string;   // Decimal → string
  enabled: boolean;
  notifySound: boolean;
  notifyDesktop: boolean;
  notifyVibrate: boolean;
  lastTriggeredAt: string | null;
}

// ... 其他 stub 接口
```

### 12.2 npm 脚本

`package.json`:
```json
{
  "scripts": {
    "dev": "next dev",
    "gen-types": "openapi-typescript http://localhost:8000/openapi.json -o src/lib/types.ts",
    "typecheck": "tsc --noEmit"
  }
}
```

### 12.3 同步流程

1. 后端修改 Pydantic schema
2. 重启后端
3. 前端跑 `npm run gen-types`(覆盖 stub)
4. 前端 `npm run typecheck` 看哪些字段变了
5. 同步修改组件代码

### 12.4 启动顺序(README 明确)

```
1. 启动 backend:cd backend && uv run uvicorn app.main:app --reload --port 8000
2. 启动 frontend:cd frontend && npm run gen-types && npm run dev
3. 访问 http://localhost:5173
```

> **关键**:`npm run gen-types` 失败时(后端未启动),保留 stub,前端可继续开发。

### 12.5 TypeScript 严格性(v1.3 新增)

> **盲点**:stub 里金额用 `number` 是**类型错误**——Pydantic v2 的 `Decimal` 序列化为 JSON **字符串**。金额用 number 会静默丢精度(`0.1+0.2`)。本节统一规范。

#### 12.5.1 tsconfig 严格项

```jsonc
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,     // 数组/对象索引可能 undefined
    "exactOptionalPropertyTypes": true,   // 可选属性不能赋 undefined
    "verbatimModuleSyntax": true,         // import type 强制分离
    "noImplicitOverride": true
  }
}
```

#### 12.5.2 金额类型规范(重要修正)

| 后端类型 | JSON 传输 | 前端 TS 类型 | 展示 |
|---|---|---|---|
| `Decimal` | **string**("10.500") | **`string`** | `decimalFormat()` → "10.50" |
| `int`(股数) | number | number | 千分位 |
| `float`(涨跌幅) | number | number | toFixed(2) |

stub 修正示例:

```typescript
export interface Position {
  stockCode: string;
  stockName: string | null;
  shares: number;                      // int → number
  avgCost: string;                     // Decimal → string ← 修正
  totalCost: string;                   // Decimal → string ← 修正
  currentPrice: string | null;         // ← 修正
  todayPnl: string | null;             // ← 修正
  todayPnlPct: number | null;          // float → number
  floatingPnl: string | null;          // ← 修正
  floatingPnlPct: number | null;
}
```

- 金额运算**禁止**在 JS 里做(由后端算好返回)
- `decimalFormat(value: string)` 工具:字符串解析 + 千分位 + 2 位小数,不做算术

#### 12.5.3 禁止 `any` 规范

- 组件/业务代码:禁止显式 `any`,用 `unknown` + 类型守卫收窄
- `snakeToCamel`:入参 `unknown`,返回经过 `as const` 或逐字段断言
- SSE 事件数据:`unknown` → `parseEvent(data)` 用 Zod 校验后分发
- 例外:`React.lazy`、`echarts` 初始化等边界,用 `// eslint-disable-next-line @typescript-eslint/no-explicit-any` + 注释理由

#### 12.5.4 stub 与生成类型的差异防护

- stub 与真实生成类型不一致 → `tsc` 编译错(设计如此,是安全网,不是 bug)
- 同步流程(12.3)固定执行 `npm run typecheck`,把差异当成"改字段提醒"
- 新增字段时先改 stub 再实现,保证开发期类型完整

#### 12.5.5 校验

```bash
npm run typecheck   # tsc --noEmit,严格模式零错误
npx eslint .        # no-explicit-any 零警告
```

---

## 第 13 章 性能优化

### 13.1 React.memo

```tsx
// components/charts/PnlHeatmap.tsx
import { memo } from 'react';

export const PnlHeatmap = memo(function PnlHeatmap({ grid }: { grid: PnlGrid }) {
  // 21 档渲染
});
```

### 13.2 列表虚拟滚动(> 50 行)

```tsx
import { useVirtualizer } from '@tanstack/react-virtual';

// 流水列表 > 50 行时启用
const virtualizer = useVirtualizer({
  count: transactions.length,
  getScrollElement: () => parentRef.current,
  estimateSize: () => 48,
});
```

### 13.3 代码分割(App Router 自动)

- 每个路由自动分割
- 弹窗组件:`React.lazy` + Suspense

### 13.4 图片优化

```tsx
import Image from 'next/image';

<Image src="/logo.png" width={120} height={40} alt="盘后诊股室" />
```

---

## 第 14 章 可测试性

### 14.1 测试工具

- `vitest`:单元测试
- `@testing-library/react`:组件测试
- `@testing-library/user-event`:交互模拟

### 14.2 必须测试的组件

| 组件 | 测试重点 |
|---|---|
| `CalculatorPanel` | 输入即算、边界处理 |
| `PnlHeatmap` | 21 档渲染、悬停交互 |
| `ScoreDetail` | 三态切换(完整/加载/失败) |
| `StopLossAlert` | 必选其一、不可关闭遮罩 |
| `useStopLossChecker` | 触发条件、每天最多 1 次 |

### 14.3 测试示例

```typescript
// __tests__/PnlHeatmap.test.tsx
import { render, screen } from '@testing-library/react';
import { PnlHeatmap } from '@/components/charts/PnlHeatmap';

const mockGrid = [
  { pct: -10, price: 9.30, market_value: 13950, pnl: -1550 },
  // ...
];

describe('PnlHeatmap', () => {
  it('renders 21 bars', () => {
    render(<PnlHeatmap grid={mockGrid} />);
    expect(screen.getAllByTestId('pnl-bar')).toHaveLength(21);
  });
  
  it('highlights current price position', () => {
    render(<PnlHeatmap grid={mockGrid} currentPct={0} />);
    expect(screen.getByTestId('current-price-marker')).toBeInTheDocument();
  });
});
```

---

## 第 15 章 部署与运维

### 15.1 启动

```bash
npm run dev   # Next.js dev server :5173
```

### 15.2 与后端启动顺序

```bash
# 必须先启后端
cd ../backend && uv run uvicorn app.main:app --reload --port 8000 &

# 再启前端
npm run dev
```

### 15.3 调试技巧

- **SSE 调试**:浏览器 DevTools → Network → EventStream 查看事件
- **API 类型不匹配**:跑 `npm run gen-types` 同步
- **主题不切换**:检查 `next-themes` Provider 是否在 layout.tsx 中

---

## 第 16 章 与 UI/UX 设计书的对齐

### 16.1 引用清单

本前端架构严格遵循 `ui-ux-design.md` 的:
- 视觉系统(第二章):CSS 变量映射到 Tailwind config
- 信息架构(第三章):路由结构对应
- 关键页面(第四章):页面组件组装
- 核心组件(第五章):组件清单 + 设计
- 状态设计(第十一章):加载/错误/空状态
- 品牌声音(第十二章):文案语气

### 16.2 设计 tokens 映射

```typescript
// tailwind.config.ts
export default {
  theme: {
    extend: {
      colors: {
        // 主色调
        'bg-base': 'var(--bg-base)',
        'bg-surface': 'var(--bg-surface)',
        'text-primary': 'var(--text-primary)',
        // 强调色
        'accent-primary': '#2563EB',
        // 状态色(涨跌)
        'status-up': 'var(--status-up)',
        'status-down': 'var(--status-down)',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
};
```

### 16.3 组件对照表

| UI 设计书组件 | 前端实现 |
|---|---|
| `StockQuoteCard`(4.1) | `components/transaction/StockQuoteCard.tsx` |
| `CalculatorPanel`(4.2) | `components/calculator/CalculatorPanel.tsx` |
| `PnlHeatmap`(5.3) | `components/charts/PnlHeatmap.tsx` |
| `TransactionForm`(4.3) | `components/transaction/TransactionForm.tsx` |
| `ScoreDetail`(4.4) | `components/signal/ScoreDetail.tsx` |
| `StopLossModal`(4.6) | `components/stop-loss/StopLossModal.tsx` |
| `StopLossAlert`(4.7) | `components/stop-loss/StopLossAlert.tsx` |
| `AnnualReportCard`(4.8) | `components/annual-report/AnnualReportCard.tsx` |

---

## 第 17 章 决策记录

| # | 决策项 | 选择 | 理由 |
|---|---|---|---|
| A1 | 框架 | Next.js 14 App Router | 现代最佳实践 |
| A2 | 渲染策略 | MVP 全部 Client Components | 交互密集,简化 |
| A3 | 状态管理 | Zustand | 轻量,够用 |
| A4 | 表单 | React Hook Form + Zod | 性能 + 类型安全 |
| A5 | 类型生成 | openapi-typescript | 单一来源 |
| A6 | 主题 | next-themes + CSS 变量 | 标准做法 |
| A7 | SSE 客户端 | 自研 EventSource 封装 | 无需第三方 |
| A8 | 定时轮询 | setInterval + useEffect | 简单够用 |
| A9 | 通知 | Web Notification + Vibration | 标准 API |
| A10 | 性能优化 | React.memo + 虚拟滚动 + Next.js 自动分割 | 按需启用 |
| A11 | 测试 | vitest + @testing-library/react | 现代化 |
| A12 | 路由结构 | 5 个页面 + 年度账单详情 | MVP 范围 |
| A13 | 状态分层 | ui/business/pages 三层 | 复用边界清晰 |
| A14 | 暗色图表适配 | ECharts 销毁重建双主题 + SVG 全 CSS 变量 | v1.3 盲点 15 |
| A15 | 金额类型 | Decimal → JSON string,前端 string + decimalFormat | v1.3 盲点 16(修 number bug) |

---

**文档结束。**