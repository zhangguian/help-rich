import { type HTMLAttributes } from 'react';

import clsx from 'clsx';

/**
 * 共享格式化工具(v0.7 Dark Terminal)
 *
 * 收敛此前散落全站的重复实现:
 * - pctClass  5 份(page.tsx / WatchList / PositionStatsCards / PositionSummaryTable / WatchlistPanel),签名 3 种
 * - pct()     4 份(sector-fund-flow / AnalysisPanel / MarketOverviewPage / ScoreBreakdown)
 * - fmtYi()   2 份(sector-fund-flow / ScreenerPanel)
 * - MONTH_LABEL 2 份(provider-stats / annual-report)
 *
 * 全部统一接受 null | undefined,避免调用方各自写空值分支。
 */

/** 涨跌幅 → 文字色类。红涨绿跌,零值走中性色。 */
export function pctClass(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return 'text-text-ter';
  if (v > 0) return 'text-up';
  if (v < 0) return 'text-down';
  return 'text-text-ter';
}

/** 涨跌幅 → chip 底色类 */
export function pctChipClass(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return 'bg-bg-subtle text-text-ter';
  if (v > 0) return 'bg-up-bg text-up';
  if (v < 0) return 'bg-down-bg text-down';
  return 'bg-bg-subtle text-text-ter';
}

/** 百分比格式化。带符号(冗余编码,服务红绿色盲)。 */
export function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return '--';
  return `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`;
}

/** 金额(元) → 亿 */
export function fmtYi(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return '--';
  return (v / 1e8).toLocaleString('zh-CN', { maximumFractionDigits: digits });
}

/** 金额(亿) → 万亿 / 亿自动切换 */
export function fmtAmountYi(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return '--';
  if (Math.abs(v) >= 10000) {
    return `${(v / 10000).toLocaleString('zh-CN', { maximumFractionDigits: digits })} 万亿`;
  }
  return `${v.toLocaleString('zh-CN', { maximumFractionDigits: digits })} 亿`;
}

/** 保留小数 + 千分位 */
export function decimal(v: number | string | null | undefined, digits = 1): string {
  if (v == null || v === '') return '--';
  const n = typeof v === 'string' ? Number(v) : v;
  if (Number.isNaN(n)) return '--';
  return n.toLocaleString('zh-CN', { maximumFractionDigits: digits });
}

export const MONTH_LABEL: readonly string[] = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'];

/** 月序号(1-12)→ 中文月名;越界返回 '-' */
export function monthLabel(m: number | null | undefined): string {
  if (m == null || m < 1 || m > 12) return '-';
  return MONTH_LABEL[m - 1] ?? '-';
}

/** Logo 章渐变色(按代码哈希取色,稳定不变) */
const CHIP_COLORS = [
  'from-blue-500 to-sky-400',
  'from-violet-500 to-purple-400',
  'from-cyan-500 to-teal-400',
  'from-amber-500 to-orange-400',
  'from-rose-500 to-pink-400',
];

export function chipColor(code: string): string {
  let h = 0;
  for (let i = 0; i < code.length; i++) h = (h * 31 + code.charCodeAt(i)) >>> 0;
  return CHIP_COLORS[h % CHIP_COLORS.length] ?? CHIP_COLORS[0]!;
}
