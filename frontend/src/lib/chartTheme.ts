'use client';

import { useEffect, useMemo, useState } from 'react';

import { THEME_EVENT } from '@/lib/theme';

/**
 * 图表主题(v0.8 Trading Desk)
 *
 * 运行时从 CSS 变量读取,使图表与 UI 共用同一真相源 ——
 * 改 src/styles/tokens.css 即改图表,无需二次改图表代码。
 *
 * 动机:此前 4 个图表组件共 53 处硬编码色,全部绕开 token;
 * 其中三个 lightweight-charts 组件统一用 #64748b(slate-500 中灰)做轴标签,
 * 在深底上对比度不足。
 *
 * **v0.8 改动**:新增纸面终端主题后,主题不再是「只有一种」——
 * 组件在挂载时读一次会漏掉切主题。所以这里监听 `rich-theme-change` 事件
 * (由 src/lib/theme.ts 广播)重新读取,保证 UI 变浅色时图表也同步。
 */

export interface ChartTheme {
  /** 轴标签 / 图例文字 */
  text: string;
  /** 网格线 */
  grid: string;
  /** 坐标轴边框 */
  axis: string;
  /** 涨 / 跌(与 UI 行情色同源) */
  up: string;
  down: string;
  ma5: string;
  ma10: string;
  ma20: string;
  ma60: string;
  bollUp: string;
  bollMid: string;
  bollDn: string;
  macdDif: string;
  macdDea: string;
  macdHistPos: string;
  macdHistNeg: string;
  kdjK: string;
  kdjD: string;
  kdjJ: string;
}

const FALLBACK: ChartTheme = {
  text: '#8fa0b8',
  grid: 'rgba(159, 176, 195, 0.1)',
  axis: 'rgba(159, 176, 195, 0.28)',
  up: '#f6465d',
  down: '#0ecb81',
  ma5: '#f0883e',
  ma10: '#a78bfa',
  ma20: '#3b9eff',
  ma60: '#22c55e',
  bollUp: 'rgba(246, 70, 93, 0.72)',
  bollMid: 'rgba(143, 160, 184, 0.8)',
  bollDn: 'rgba(14, 235, 129, 0.72)',
  macdDif: '#f5a524',
  macdDea: '#818cf8',
  macdHistPos: 'rgba(246, 70, 93, 0.55)',
  macdHistNeg: 'rgba(14, 235, 129, 0.55)',
  kdjK: '#22d3ee',
  kdjD: '#f6465d',
  kdjJ: '#8fa0b8',
};

function readVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function readTheme(): ChartTheme {
  const c = (name: string, fb: string) => readVar(name, fb);
  const up = c('--status-up', FALLBACK.up);
  const down = c('--status-down', FALLBACK.down);
  return {
    text: c('--chart-text', FALLBACK.text),
    grid: c('--chart-grid', FALLBACK.grid),
    axis: c('--chart-axis', FALLBACK.axis),
    up,
    down,
    ma5: c('--chart-ma5', FALLBACK.ma5),
    ma10: c('--chart-ma10', FALLBACK.ma10),
    ma20: c('--chart-ma20', FALLBACK.ma20),
    ma60: c('--chart-ma60', FALLBACK.ma60),
    bollUp: c('--chart-boll-up', FALLBACK.bollUp),
    bollMid: c('--chart-boll-mid', FALLBACK.bollMid),
    bollDn: c('--chart-boll-dn', FALLBACK.bollDn),
    macdDif: c('--chart-macd-dif', FALLBACK.macdDif),
    macdDea: c('--chart-macd-dea', FALLBACK.macdDea),
    macdHistPos: c('--chart-macd-hist-pos', FALLBACK.macdHistPos),
    macdHistNeg: c('--chart-macd-hist-neg', FALLBACK.macdHistNeg),
    kdjK: c('--chart-kdj-k', FALLBACK.kdjK),
    kdjD: up,
    kdjJ: c('--chart-kdj-j', FALLBACK.kdjJ),
  };
}

/**
 * 读取当前图表主题。
 * 首次渲染返回 FALLBACK(与 tokens.css 同值,避免闪烁);
 * 主题切换时通过 `rich-theme-change` 事件重新读取。
 */
export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(FALLBACK);
  useEffect(() => {
    const sync = () => setTheme(readTheme());
    sync();
    window.addEventListener(THEME_EVENT, sync);
    return () => window.removeEventListener(THEME_EVENT, sync);
  }, []);
  // 稳定引用:图表 effect 依赖 COLOR,若每次渲染新建对象会无限重建图表
  return useMemo(() => theme, [theme]);
}
