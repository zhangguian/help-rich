'use client';

import { type ReactNode } from 'react';

import clsx from 'clsx';

import { TermHint } from '@/components/ui/TermHint';
import { GlassCard } from '@/components/ui/GlassCard';
import { decimalFormat } from '@/lib/decimalFormat';
import { pctClass, pctChipClass } from '@/lib/format';
import type { Position } from '@/lib/types';

/**
 * 持仓统计卡行(企业版工作台,参考设计稿统计卡)
 * 一行 3 卡:图标章 + 大数字 + 说明 + 迷你柱状图(柱 = 各持仓贡献,真实数据)
 * 传入 extra 时扩展为 4 列(第 4 卡由调用方注入,如 AI 助手卡)
 */

/** 迷你柱状图:每根柱 = 一只持仓的数值;红涨绿跌或品牌蓝 */
function MiniBars({ values, tone }: { values: number[]; tone: 'value' | 'pnl' }) {
  if (values.length === 0) return null;
  const max = Math.max(...values.map((v) => Math.abs(v)), 1e-9);
  return (
    <div className="flex items-end gap-1 h-10 mt-3" aria-hidden>
      {values.slice(0, 16).map((v, i) => (
        <div
          key={i}
          className="flex-1 rounded-[3px] min-w-[4px]"
          style={{
            height: `${Math.max((Math.abs(v) / max) * 100, 10)}%`,
            backgroundColor:
              tone === 'value'
                ? 'rgb(var(--accent-rgb) / 0.28)'
                : v >= 0
                  ? 'rgb(var(--up-rgb) / 0.32)'
                  : 'rgb(var(--down-rgb) / 0.32)',
          }}
        />
      ))}
    </div>
  );
}

const ICON_CHIP = 'w-10 h-10 rounded-2xl flex items-center justify-center text-lg shrink-0';

export function PositionStatsCards({
  positions,
  extra,
}: {
  positions: Position[];
  /** 第 4 卡插槽(如 AI 助手卡);传入后网格变 4 列 */
  extra?: ReactNode;
}) {
  const hasQuotes = positions.some((p) => p.currentPrice != null);

  const totalMarketValue = positions.reduce(
    (sum, p) =>
      p.currentPrice != null ? sum + p.shares * Number(p.currentPrice) : sum,
    0,
  );
  const totalCost = positions.reduce((sum, p) => sum + Number(p.totalCost), 0);
  const totalFloatingPnl = positions.reduce(
    (sum, p) => sum + Number(p.floatingPnl ?? 0),
    0,
  );
  const totalTodayPnl = positions.reduce(
    (sum, p) => sum + Number(p.todayPnl ?? 0),
    0,
  );
  const ratioPct =
    totalCost > 0 ? (totalFloatingPnl / totalCost) * 100 : null;

  const pctBadge = (v: number) =>
    `px-1.5 py-0.5 rounded text-[11px] font-mono font-semibold ${pctChipClass(v)}`;

  // 迷你柱:各持仓贡献(与卡内大数字同源)
  const marketValues = positions.map((p) =>
    p.currentPrice != null ? p.shares * Number(p.currentPrice) : 0,
  );
  const floatingPnls = positions.map((p) => Number(p.floatingPnl ?? 0));
  const todayPnls = positions.map((p) => Number(p.todayPnl ?? 0));

  return (
    <div className={clsx('grid grid-cols-1 sm:grid-cols-3 gap-5', extra && 'xl:grid-cols-4')}>
      {/* 总市值 */}
      <GlassCard padding="md" className="min-h-[150px] flex flex-col">
        <div className="flex items-center gap-3">
          <span className={`${ICON_CHIP} bg-accent-subtle`}>💼</span>
          <div className="text-xs text-text-sec inline-flex items-center">
            总市值<TermHint term="total_market_value" />
          </div>
          <span className="ml-auto px-2 py-0.5 rounded-lg bg-bg-subtle text-text-ter text-[11px]">
            {positions.length} 只
          </span>
        </div>
        <div className="text-[26px] font-mono font-bold text-text-pri mt-3 leading-none">
          {hasQuotes ? `¥${decimalFormat(totalMarketValue.toFixed(2))}` : '--'}
        </div>
        <div className="text-xs text-text-ter mt-1.5">
          {hasQuotes ? 'Σ 股数 × 现价' : '行情暂不可用'}
        </div>
        {hasQuotes && <MiniBars values={marketValues} tone="value" />}
      </GlassCard>

      {/* 总浮盈(占比%) */}
      <GlassCard padding="md" className="min-h-[150px] flex flex-col">
        <div className="flex items-center gap-3">
          <span className={`${ICON_CHIP} bg-violet-100`}>📊</span>
          <div className="text-xs text-text-sec inline-flex items-center">
            总浮盈<TermHint term="total_floating_pnl" />
          </div>
          {hasQuotes && ratioPct != null && (
            <span className={`ml-auto ${pctBadge(ratioPct)}`}>
              {ratioPct >= 0 ? '+' : ''}
              {ratioPct.toFixed(2)}%
            </span>
          )}
        </div>
        <div className={`text-[26px] font-mono font-bold mt-3 leading-none ${pctClass(totalFloatingPnl)}`}>
          {hasQuotes
            ? `${totalFloatingPnl >= 0 ? '+' : ''}¥${decimalFormat(totalFloatingPnl.toFixed(2))}`
            : '--'}
        </div>
        <div className="text-xs text-text-ter mt-1.5 inline-flex items-center">
          {hasQuotes && ratioPct != null ? (
            <>
              占比<TermHint term="pnl_ratio" /> {ratioPct >= 0 ? '+' : ''}
              {ratioPct.toFixed(2)}%
            </>
          ) : (
            '行情暂不可用'
          )}
        </div>
        {hasQuotes && <MiniBars values={floatingPnls} tone="pnl" />}
      </GlassCard>

      {/* 今日盈亏 */}
      <GlassCard padding="md" className="min-h-[150px] flex flex-col">
        <div className="flex items-center gap-3">
          <span className={`${ICON_CHIP} bg-amber-100`}>⚡</span>
          <div className="text-xs text-text-sec inline-flex items-center">
            今日盈亏<TermHint term="today_pnl" />
          </div>
        </div>
        <div className={`text-[26px] font-mono font-bold mt-3 leading-none ${pctClass(totalTodayPnl)}`}>
          {hasQuotes
            ? `${totalTodayPnl >= 0 ? '+' : ''}¥${decimalFormat(totalTodayPnl.toFixed(2))}`
            : '--'}
        </div>
        <div className="text-xs text-text-ter mt-1.5">
          {hasQuotes ? 'Σ 现价 − 昨收' : '行情暂不可用'}
        </div>
        {hasQuotes && <MiniBars values={todayPnls} tone="pnl" />}
      </GlassCard>
      {extra}
    </div>
  );
}
