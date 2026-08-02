'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { TermHint } from '@/components/ui/TermHint';
import { apiGet } from '@/lib/api';
import { decimalFormat } from '@/lib/decimalFormat';
import type { MarketOverview } from '@/lib/types';

/**
 * 大盘盯盘横向卡片(roadmap §3.9)
 *
 * - 三大主指:上证 / 深证 / 创业板
 * - 右侧:领涨 / 领跌各 top3
 * - 60s 自动刷新 + 手动 🔄 按钮
 * - 失败:整条灰显 + 「行情暂不可用」+ 重试按钮
 * - 数据来自 GET /api/market/overview
 */
const REFRESH_INTERVAL_MS = 60_000;
const STALE_AFTER_MS = 90_000; // 超过 90s 视为 staleness,角标小点提示

export function MarketOverviewBar() {
  const [data, setData] = useState<MarketOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastFetchAt, setLastFetchAt] = useState<number>(0);
  const [tick, setTick] = useState(0); // 触发 staleness 重算

  const fetchOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await apiGet<MarketOverview>('/market/overview');
      setData(d);
      setLastFetchAt(Date.now());
    } catch (e) {
      const msg =
        (e as { response?: { data?: { detail?: { message?: string } } } })
          ?.response?.data?.detail?.message ??
        (e instanceof Error ? e.message : null) ??
        '行情暂不可用';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOverview();
    const interval = setInterval(fetchOverview, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchOverview]);

  // 每秒更新 staleness 角标(>90s 显示)
  useEffect(() => {
    const t = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const stale = lastFetchAt > 0 && Date.now() - lastFetchAt > STALE_AFTER_MS;
  void tick; // 触发依赖收集

  return (
    <div className="shrink-0 liquid-glass rounded-2xl px-4 py-2.5 flex items-center gap-4">
      {/* 三大指数 */}
      <div className="flex items-center gap-5 min-w-0 overflow-x-auto">
        <span className="text-xs text-text-ter font-medium shrink-0 inline-flex items-center">
          大盘<TermHint term="market_index" />
        </span>
        {loading && !data ? (
          <SkeletonIndexes />
        ) : error && !data ? (
          <span className="text-xs text-down">⚠ {error}</span>
        ) : (
          (data?.indexes ?? []).map((idx) => (
            <IndexCell key={idx?.code ?? Math.random()} idx={idx} />
          ))
        )}
      </div>

      {/* 右侧:领涨/领跌 + 刷新按钮 */}
      <div className="flex items-center gap-3 shrink-0 ml-auto">
        {!error && data && (
          <>
            <MoversColumn
              label="领涨"
              term="gainer"
              items={data.gainers}
              tone="up"
            />
            <div className="w-px h-7 bg-white/10" />
            <MoversColumn
              label="领跌"
              term="loser"
              items={data.losers}
              tone="down"
            />
          </>
        )}
        <button
          type="button"
          onClick={fetchOverview}
          disabled={loading}
          className={clsx(
            'inline-flex items-center justify-center w-7 h-7 rounded-full',
            'text-text-ter hover:text-text-pri hover:bg-white/5 transition-colors',
            loading && 'animate-spin text-accent',
          )}
          aria-label="刷新大盘"
          title="刷新大盘(60s 自动)"
        >
          {stale && !loading && (
            <span className="absolute w-1.5 h-1.5 rounded-full bg-warn" />
          )}
          ↻
        </button>
        {error && data && (
          <button
            type="button"
            onClick={fetchOverview}
            className="text-xs text-down underline-offset-2 hover:underline"
          >
            重试
          </button>
        )}
      </div>
    </div>
  );
}

// === 指数单元 ===

function IndexCell({ idx }: { idx: { code: string; name: string; currentPrice: string; changePct: number } | null }) {
  if (!idx) {
    return (
      <div className="shrink-0">
        <div className="text-xs text-text-ter">--</div>
        <div className="text-lg font-mono text-text-ter">--</div>
      </div>
    );
  }
  const pct = idx.changePct;
  const colorCls =
    pct > 0
      ? 'text-up'
      : pct < 0
        ? 'text-down'
        : 'text-text-pri';
  const sign = pct > 0 ? '+' : '';
  return (
    <div className="shrink-0">
      <div className="text-xs text-text-ter truncate max-w-[5rem]">{idx.name}</div>
      <div className={clsx('text-lg font-mono font-semibold leading-tight', colorCls)}>
        ¥{decimalFormat(idx.currentPrice)}
      </div>
      <div className={clsx('text-[11px] font-mono', colorCls)}>
        {sign}{pct.toFixed(2)}%
      </div>
    </div>
  );
}

function SkeletonIndexes() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <div key={i} className="shrink-0 space-y-1">
          <div className="h-3 w-10 rounded bg-white/5 animate-pulse" />
          <div className="h-5 w-16 rounded bg-white/10 animate-pulse" />
          <div className="h-3 w-12 rounded bg-white/5 animate-pulse" />
        </div>
      ))}
    </>
  );
}

// === 领涨/领跌列 ===

function MoversColumn({
  label,
  term,
  items,
  tone,
}: {
  label: string;
  term: 'gainer' | 'loser';
  items: { code: string; name: string; currentPrice: string; changePct: number }[];
  tone: 'up' | 'down';
}) {
  return (
    <div className="flex flex-col gap-0.5 min-w-[5rem]">
      <span
        className={clsx(
          'text-[10px] uppercase tracking-wide inline-flex items-center',
          tone === 'up' ? 'text-up' : 'text-down',
        )}
      >
        {label}<TermHint term={term} />
      </span>
      {items.length === 0 ? (
        <span className="text-[10px] text-text-ter">暂无</span>
      ) : (
        items.map((m) => (
          <div key={m.code} className="flex items-baseline gap-1.5 text-[11px] font-mono">
            <span className="text-text-pri truncate max-w-[4rem]">{m.name}</span>
            <span className={tone === 'up' ? 'text-up' : 'text-down'}>
              {m.changePct > 0 ? '+' : ''}{m.changePct.toFixed(2)}%
            </span>
          </div>
        ))
      )}
    </div>
  );
}