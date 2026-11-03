'use client';

import Link from 'next/link';

import { useEffect } from 'react';

import clsx from 'clsx';

import { intFormat, priceFormat } from '@/lib/decimalFormat';
import { useTReminderStore } from '@/stores/useTReminderStore';

/**
 * 左栏置顶「补T提醒」清单
 *
 * 为什么放第一位:补T是有时效的动作 —— 今天卖出的票,明天要在更低价接回;
 * 今天买进的票,涨上去要卖掉。错过一天就是一次失败的高抛低吸。
 * 它比任何浏览型入口都更该被第一眼看到。
 *
 * 两组挂单:
 * - 待接回(反T,先卖后买)—— 显示建议接回价 ≤
 * - 待卖出(正T,先买后卖)—— 显示建议卖出价 ≥
 *
 * 折叠态(48px 图标轨)只留一个 🔁 图标 + 条数徽标;展开态直接列出挂单清单,
 * 不用点进去就能看到「哪只、接多少、什么价接」。
 */
export function TReminderRailCard({ collapsed }: { collapsed: boolean }) {
  const items = useTReminderStore((s) => s.items);
  const forwardItems = useTReminderStore((s) => s.forwardItems);
  const load = useTReminderStore((s) => s.load);
  const lastLoadedAt = useTReminderStore((s) => s.lastLoadedAt);

  useEffect(() => {
    void load();
  }, [load]);

  const count = items.length + forwardItems.length;

  if (collapsed) {
    return (
      <Link
        href="/t-reminders"
        title={count > 0 ? `做T挂单:${count} 只` : '补T提醒'}
        className="relative mx-1.5 mb-2 flex items-center justify-center py-1.5 rounded text-[14px] transition-colors hover:bg-bg-subtle"
      >
        <span className={clsx('grayscale opacity-60', count > 0 && 'grayscale-0')}>🔁</span>
        {count > 0 && (
          <span
            className="absolute top-0 right-1 min-w-[15px] h-[15px] px-[3px] rounded-full bg-accent text-bg-base text-[10px] font-semibold leading-[15px] text-center"
            aria-label={`${count} 只挂单`}
          >
            {count}
          </span>
        )}
      </Link>
    );
  }

  return (
    <div className="mx-1.5 mb-2 rounded border border-accent/40 bg-accent-subtle overflow-hidden">
      <Link
        href="/t-reminders"
        className="flex items-center justify-between px-2 py-1.5 text-[12px] font-semibold text-accent hover:bg-bg-subtle"
        title="补T提醒 — 还没配上的做T单"
      >
        <span>🔁 补T提醒</span>
        <span className="font-mono text-[11px]">
          {count > 0 ? `${count} 只` : lastLoadedAt ? '无' : '…'}
        </span>
      </Link>
      {count > 0 && (
        <ul className="border-t border-border-def">
          {items.map((it) => {
            // 左栏给的是**一档建议价**(最容易成交、该动手的那一档),不亏本线放 title 里
            const shown = it.suggestedPrice ?? it.price;
            return (
              <li key={`r-${it.stockCode}`}>
                <Link
                  href={`/t-reminders?code=${encodeURIComponent(it.stockCode)}`}
                  className="flex items-baseline justify-between gap-1 px-2 py-1 text-[11px] text-text-sec hover:bg-bg-subtle hover:text-text-pri"
                  title={
                    `${it.stockName ?? ''} ${it.stockCode} — 接回 ${it.shares} 股\n` +
                    `一档建议接回价 ≤${priceFormat(shown)}(不亏本线 ${priceFormat(it.price)})` +
                    (it.preAlertPrice !== null
                      ? `\n预警线 ≤${priceFormat(it.preAlertPrice)}(到价前先提醒准备${
                          it.preAlertDistancePct !== null
                            ? ` · 还差 ${it.preAlertDistancePct.toFixed(2)}%`
                            : ''
                        })`
                      : '')
                  }
                >
                  <span className="font-mono text-text-pri truncate">{it.stockCode}</span>
                  <span className="font-mono shrink-0">
                    {intFormat(it.shares)}
                    <span className="text-text-ter"> @ </span>
                    <span className="text-accent">≤{priceFormat(shown)}</span>
                  </span>
                </Link>
              </li>
            );
          })}
          {forwardItems.map((it) => {
            const shown = it.suggestedPrice ?? it.price;
            return (
              <li key={`f-${it.stockCode}`}>
                <Link
                  href={`/t-reminders?code=${encodeURIComponent(it.stockCode)}`}
                  className="flex items-baseline justify-between gap-1 px-2 py-1 text-[11px] text-text-sec hover:bg-bg-subtle hover:text-text-pri"
                  title={
                    `${it.stockName ?? ''} ${it.stockCode} — 卖出 ${it.shares} 股\n` +
                    `一档建议卖出价 ≥${priceFormat(shown)}(买入均价 ${priceFormat(it.price)})` +
                    (it.preAlertPrice !== null
                      ? `\n预警线 ≥${priceFormat(it.preAlertPrice)}(到价前先提醒准备${
                          it.preAlertDistancePct !== null
                            ? ` · 还差 ${it.preAlertDistancePct.toFixed(2)}%`
                            : ''
                        })`
                      : '')
                  }
                >
                  <span className="font-mono text-text-pri truncate">{it.stockCode}</span>
                  <span className="font-mono shrink-0">
                    {intFormat(it.shares)}
                    <span className="text-text-ter"> @ </span>
                    <span className="text-accent">≥{priceFormat(shown)}</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
