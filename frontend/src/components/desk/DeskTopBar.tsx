'use client';

import { useEffect, useState } from 'react';

import clsx from 'clsx';

import type { MarketIndex } from '@/lib/types';
import { getTheme, setTheme, type ThemeMode } from '@/lib/theme';

/**
 * 交易台顶栏(v0.8)
 *
 * 一行放下四件事,**不设第二行**,把垂直空间全留给行情:
 * 1. 视角切换(自选 / 关注 / 持仓)—— 放在最左,紧贴列表栏,点完眼睛不用横跨屏幕
 * 2. 三大指数 ticker —— 常驻可见,盯盘时这是最高频看的数据
 * 3. 自动刷新开关 + 倒计时
 * 4. 主题切换(深色终端 / 纸面终端)
 *
 * 旧版把指数做成右上角三张独立小卡、刷新开关塞在另一处,
 * 视觉上散成三堆,盯盘时反而要多处扫视 —— 这里收成一条。
 */

export type DeskTab = 'watch' | 'favorite' | 'position';

const TABS: { key: DeskTab; label: string }[] = [
  { key: 'watch', label: '自选' },
  { key: 'favorite', label: '★ 关注' },
  { key: 'position', label: '持仓' },
];

export function DeskTopBar({
  tab,
  onTabChange,
  indexes,
  autoRefresh,
  secondsLeft,
  onToggleRefresh,
  dateStr,
}: {
  tab: DeskTab;
  onTabChange: (t: DeskTab) => void;
  indexes: MarketIndex[];
  autoRefresh: boolean;
  secondsLeft: number;
  onToggleRefresh: () => void;
  dateStr: string;
}) {
  const [theme, setThemeState] = useState<ThemeMode>('dark');
  useEffect(() => setThemeState(getTheme()), []);

  const toggleTheme = () => {
    const next: ThemeMode = theme === 'light' ? 'dark' : 'light';
    setTheme(next);
    setThemeState(next);
  };

  return (
    <header className="shrink-0 h-11 bg-bg-surface border-b border-border-def flex items-center gap-3 px-3">
      {/* 视角切换 */}
      <nav className="flex items-center gap-0.5 p-0.5 rounded-md bg-bg-subtle border border-border-def shrink-0">
        {TABS.map((t) => {
          const on = tab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => onTabChange(t.key)}
              aria-pressed={on}
              className={clsx(
                'px-2.5 py-1 rounded-sm text-xs transition-colors whitespace-nowrap',
                on
                  ? 'bg-surface-3 text-text-pri font-semibold'
                  : 'text-text-ter hover:text-text-sec',
              )}
            >
              {t.label}
            </button>
          );
        })}
      </nav>

      <span className="text-[11px] text-text-ter font-mono hidden xl:inline whitespace-nowrap">
        {dateStr}
      </span>

      {/* 指数 ticker —— 靠右排,空间不足时先让它被压缩 */}
      <div className="flex items-center gap-4 ml-auto min-w-0 overflow-hidden">
        {indexes.length === 0
          ? Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="w-24 h-4 rounded-sm bg-bg-subtle animate-pulse" />
            ))
          : indexes.slice(0, 3).map((idx) => (
              <button
                key={idx.code}
                type="button"
                onClick={() => {
                  window.location.href = '/market';
                }}
                title={`${idx.name} · 点击查看大盘详情`}
                className="flex items-baseline gap-1.5 whitespace-nowrap hover:opacity-80 transition-opacity"
              >
                <span className="text-[10.5px] text-text-ter font-mono">{idx.name}</span>
                <span className="text-[13.5px] font-mono font-semibold tabular-nums text-text-pri">
                  {idx.currentPrice}
                </span>
                <span
                  className={clsx(
                    'text-[11.5px] font-mono font-semibold tabular-nums',
                    idx.changePct > 0 ? 'text-up' : idx.changePct < 0 ? 'text-down' : 'text-text-ter',
                  )}
                >
                  {idx.changePct > 0 ? '+' : ''}
                  {idx.changePct.toFixed(2)}%
                </span>
              </button>
            ))}
      </div>

      {/* 右侧:自动刷新 + 主题 */}
      <div className="flex items-center gap-2 shrink-0 pl-3 border-l border-border-def">
        <button
          type="button"
          onClick={onToggleRefresh}
          title={autoRefresh ? '点击关闭自动刷新' : '点击开启自动刷新(15s 一次)'}
          aria-pressed={autoRefresh}
          className={clsx(
            'flex items-center gap-1.5 px-2 py-1 rounded-sm text-[11px] border transition-colors whitespace-nowrap',
            autoRefresh
              ? 'bg-accent-subtle text-accent border-accent/40 font-semibold'
              : 'bg-bg-elevated text-text-ter border-border-def hover:text-text-sec',
          )}
        >
          <span
            className={clsx(
              'w-1.5 h-1.5 rounded-full',
              autoRefresh ? 'bg-accent animate-pulse' : 'bg-text-ter',
            )}
            aria-hidden
          />
          {autoRefresh ? (secondsLeft > 0 ? `${secondsLeft}s` : '刷新中…') : '自动刷新 OFF'}
        </button>

        <button
          type="button"
          onClick={toggleTheme}
          title={theme === 'light' ? '切换到深色终端' : '切换到纸面终端(浅色)'}
          aria-label={theme === 'light' ? '切换到深色终端' : '切换到纸面终端'}
          className="w-6 h-6 rounded-sm border border-border-def bg-bg-elevated text-text-ter hover:text-accent hover:border-accent/50 transition-colors text-[11px] flex items-center justify-center"
        >
          {theme === 'light' ? '🌙' : '☀'}
        </button>
      </div>
    </header>
  );
}
