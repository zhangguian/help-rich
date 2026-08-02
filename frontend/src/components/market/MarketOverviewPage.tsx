'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { TermHint } from '@/components/ui/TermHint';
import { apiGet } from '@/lib/api';
import { decimalFormat } from '@/lib/decimalFormat';
import type {
  MainFundFlowResponse,
  MarketIndexSparks,
  MarketOverview,
  MarketSentiment,
} from '@/lib/types';

/**
 * 大盘盯盘独立 Tab 页(roadmap §3.9 v2)
 *
 * 布局:
 * - 顶部:3 张指数卡(横向,带 sparkline 迷你趋势线)
 * - 中部:「行情中心」section,3 列:
 *   - 涨跌分布(柱状图,9 档)
 *   - 板块热力图(柱状,占位 — SectorBoard 暂未内嵌,保留接口)
 *   - A 股主力净流入榜 top10(柱状图)
 * - 60s 自动刷新 + 手动 ↻
 * - 单端点失败 → 该子模块降级,其它正常
 */
const REFRESH_INTERVAL_MS = 60_000;
const STALE_AFTER_MS = 90_000;
const SPARK_W = 90;
const SPARK_H = 32;

export function MarketOverviewPage() {
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [sparks, setSparks] = useState<MarketIndexSparks | null>(null);
  const [sentiment, setSentiment] = useState<MarketSentiment | null>(null);
  const [mainFlow, setMainFlow] = useState<MainFundFlowResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastFetchAt, setLastFetchAt] = useState<number>(0);
  const [tick, setTick] = useState(0);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ov, sp, se, mf] = await Promise.all([
        apiGet<MarketOverview>('/market/overview').catch(() => null),
        apiGet<MarketIndexSparks>('/market/index-sparks?count=60').catch(() => null),
        apiGet<MarketSentiment>('/market/sentiment').catch(() => null),
        apiGet<MainFundFlowResponse>('/market/main-fund-flow?limit=10').catch(() => null),
      ]);
      setOverview(ov);
      setSparks(sp);
      setSentiment(se);
      setMainFlow(mf);
      setLastFetchAt(Date.now());
      if (!ov && !sp && !se && !mf) {
        setError('大盘数据源暂不可用');
      }
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
    fetchAll();
    const interval = setInterval(fetchAll, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchAll]);

  useEffect(() => {
    const t = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const stale = lastFetchAt > 0 && Date.now() - lastFetchAt > STALE_AFTER_MS;
  void tick;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-4">
      {/* 顶部指数卡(横向,带 sparkline) */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {(overview?.indexes ?? []).map((idx, i) => {
          const code = idx?.code ?? `idx-${i}`;
          const spark = sparks?.sparks?.[code] ?? [];
          return (
            <IndexCard
              key={code}
              idx={idx}
              spark={spark}
              loading={loading && !overview}
            />
          );
        })}
      </section>

      {/* 行情中心 */}
      <section className="liquid-glass rounded-2xl p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-text-pri">行情中心</h2>
          <div className="flex items-center gap-2 text-xs text-text-ter">
            {stale && !loading && (
              <span className="w-1.5 h-1.5 rounded-full bg-warn" title="数据可能过期" />
            )}
            <span>60s 自动刷新</span>
            <button
              type="button"
              onClick={fetchAll}
              disabled={loading}
              className={clsx(
                'inline-flex items-center justify-center w-6 h-6 rounded-full',
                'text-text-ter hover:text-text-pri hover:bg-white/5 transition-colors',
                loading && 'animate-spin text-accent',
              )}
              aria-label="刷新行情中心"
              title="刷新行情中心"
            >
              ↻
            </button>
          </div>
        </div>

        {error && !overview && !sentiment && !mainFlow && (
          <div className="text-sm text-down py-4">⚠ {error}</div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <SentimentPanel sentiment={sentiment} loading={loading && !sentiment} />
          <MainFundFlowPanel
            data={mainFlow}
            loading={loading && !mainFlow}
          />
          <PlaceholderPanel
            label="板块热力图"
            note="复用 SectorBoard(fenlei=0 / sort=netamount)"
          />
        </div>
      </section>
    </div>
  );
}

// ============ 指数卡 ============

function IndexCard({
  idx,
  spark,
  loading,
}: {
  idx: MarketOverview['indexes'][number] | null;
  spark: { date: string; close: number }[];
  loading: boolean;
}) {
  if (loading || !idx) {
    return (
      <div className="liquid-glass rounded-2xl p-4 space-y-2">
        <div className="flex items-center justify-between">
          <div className="h-5 w-16 rounded bg-white/10 animate-pulse" />
          <div className="h-8 w-24 rounded bg-white/5 animate-pulse" />
        </div>
        <div className="h-8 w-32 rounded bg-white/10 animate-pulse" />
        <div className="h-4 w-20 rounded bg-white/5 animate-pulse" />
      </div>
    );
  }
  const pct = idx.changePct;
  const colorCls =
    pct > 0 ? 'text-up' : pct < 0 ? 'text-down' : 'text-text-pri';
  const sign = pct > 0 ? '+' : '';
  const initial = idx.name.replace(/[^A-Z]/g, '').charAt(0) || idx.name.charAt(0);
  return (
    <div className="liquid-glass rounded-2xl p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div
            className={clsx(
              'w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold shrink-0',
              'bg-accent-subtle text-accent',
            )}
            aria-hidden
          >
            {initial}
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-text-pri truncate inline-flex items-center">
              {idx.name}
            </div>
            <div className="text-[10px] font-mono text-text-ter">
              {idx.code.split('.')[1]} {idx.code.split('.')[0]}
            </div>
          </div>
        </div>
        <Sparkline points={spark} pct={pct} />
      </div>
      <div className={clsx('mt-3 text-2xl font-mono font-semibold leading-none', colorCls)}>
        ¥{decimalFormat(idx.currentPrice)}
      </div>
      <div className={clsx('mt-1 text-xs font-mono', colorCls)}>
        {sign}{idx.change} {sign}{pct.toFixed(2)}%
      </div>
    </div>
  );
}

function Sparkline({
  points,
  pct,
}: {
  points: { close: number }[];
  pct: number;
}) {
  if (points.length < 2) {
    return <div style={{ width: SPARK_W, height: SPARK_H }} aria-hidden />;
  }
  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = Math.max(max - min, 1e-9);
  const stepX = SPARK_W / (closes.length - 1);
  const path = closes
    .map((c, i) => {
      const x = i * stepX;
      const y = SPARK_H - ((c - min) / range) * SPARK_H;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');
  const color = pct > 0 ? '#f43f5e' : pct < 0 ? '#4ade80' : 'rgba(148,163,184,0.7)';
  return (
    <svg
      width={SPARK_W}
      height={SPARK_H}
      viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
      aria-hidden
      className="shrink-0"
    >
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
}

// ============ 涨跌分布 ============

const BUCKET_ORDER: { key: keyof MarketSentiment['buckets']; label: string }[] = [
  { key: 'limitUp', label: '涨停' },
  { key: 'up5_10', label: '5%~+1%' },
  { key: 'up1_5', label: '+1%~0%' },
  { key: 'up0_1', label: '平盘' },
  { key: 'down0_1', label: '0%~-1%' },
  { key: 'down1_5', label: '-1%~-5%' },
  { key: 'down5_10', label: '-5%~跌停' },
];

function SentimentPanel({
  sentiment,
  loading,
}: {
  sentiment: MarketSentiment | null;
  loading: boolean;
}) {
  return (
    <div className="bg-bg-subtle rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between text-xs">
        <span className="text-text-ter uppercase tracking-wide font-medium inline-flex items-center">
          A 股涨跌分布<TermHint term="sentiment_distribution" />
        </span>
        {sentiment && (
          <span className="text-text-ter">
            成交额 ¥{decimalFormat(String(sentiment.amountYi))}亿
          </span>
        )}
      </div>
      {loading || !sentiment ? (
        <SkeletonBars />
      ) : (
        <>
          <div className="flex items-end gap-1.5 h-32">
            {BUCKET_ORDER.map(({ key, label }) => {
              const v = sentiment.buckets[key] ?? 0;
              return (
                <SentimentBar key={key} label={label} value={v} bucketKey={key} sentiment={sentiment} />
              );
            })}
          </div>
          <div className="flex items-center gap-3 text-xs">
            <div className="flex items-center gap-1.5 flex-1 min-w-0">
              <span className="text-up">上涨</span>
              <div className="flex-1 h-1.5 rounded-full bg-up/20 overflow-hidden">
                <div
                  className="h-full bg-up"
                  style={{
                    width: `${
                      sentiment.sampleSize > 0
                        ? (sentiment.upTotal / sentiment.sampleSize) * 100
                        : 0
                    }%`,
                  }}
                />
              </div>
              <span className="text-up font-mono shrink-0">{sentiment.upTotal}只</span>
            </div>
            <div className="flex items-center gap-1.5 flex-1 min-w-0">
              <span className="text-down">下跌</span>
              <div className="flex-1 h-1.5 rounded-full bg-down/20 overflow-hidden">
                <div
                  className="h-full bg-down"
                  style={{
                    width: `${
                      sentiment.sampleSize > 0
                        ? (sentiment.downTotal / sentiment.sampleSize) * 100
                        : 0
                    }%`,
                  }}
                />
              </div>
              <span className="text-down font-mono shrink-0">{sentiment.downTotal}只</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function SentimentBar({
  label,
  value,
  bucketKey,
  sentiment,
}: {
  label: string;
  value: number;
  bucketKey: keyof MarketSentiment['buckets'];
  sentiment: MarketSentiment;
}) {
  const max = Math.max(...BUCKET_ORDER.map((b) => sentiment.buckets[b.key] ?? 0), 1);
  const heightPct = (value / max) * 100;
  const colorCls =
    bucketKey === 'flat'
      ? 'bg-text-ter/50'
      : bucketKey === 'limitUp' || bucketKey.startsWith('up')
        ? 'bg-up'
        : 'bg-down';
  return (
    <div className="flex-1 flex flex-col items-center gap-1 min-w-0">
      <div className="w-full h-full flex items-end">
        <div
          className={clsx('w-full rounded-t-sm transition-all', colorCls)}
          style={{ height: `${Math.max(heightPct, value > 0 ? 4 : 0)}%` }}
          title={`${label}: ${value}`}
        />
      </div>
      <div className="text-[10px] text-text-ter font-mono">{value}</div>
      <div className="text-[9px] text-text-ter truncate w-full text-center">{label}</div>
    </div>
  );
}

function SkeletonBars() {
  return (
    <div className="flex items-end gap-1.5 h-32">
      {[0, 1, 2, 3, 4, 5, 6].map((i) => (
        <div key={i} className="flex-1 h-full flex flex-col justify-end">
          <div className="w-full h-1/3 rounded-t-sm bg-white/5 animate-pulse" />
          <div className="mt-1 h-2 w-full rounded bg-white/5 animate-pulse" />
        </div>
      ))}
    </div>
  );
}

// ============ 主力净流入 ============

function MainFundFlowPanel({
  data,
  loading,
}: {
  data: MainFundFlowResponse | null;
  loading: boolean;
}) {
  return (
    <div className="bg-bg-subtle rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between text-xs">
        <span className="text-text-ter uppercase tracking-wide font-medium inline-flex items-center">
          A 股主力净流入<TermHint term="main_fund_flow" />
        </span>
        {data && <span className="text-text-ter">top {data.limit}</span>}
      </div>
      {loading || !data ? (
        <SkeletonBars />
      ) : data.items.length === 0 ? (
        <div className="text-xs text-text-ter py-6 text-center">暂无数据</div>
      ) : (
        <MainFundFlowChart items={data.items} />
      )}
    </div>
  );
}

function MainFundFlowChart({ items }: { items: { code: string; name: string; netamountYi: number }[] }) {
  const max = Math.max(...items.map((i) => Math.abs(i.netamountYi)), 1);
  return (
    <div className="space-y-1.5">
      {items.map((it, i) => {
        const isUp = it.netamountYi > 0;
        const wPct = (Math.abs(it.netamountYi) / max) * 100;
        return (
          <div key={it.code} className="flex items-center gap-2 text-xs">
            <span className="text-text-ter font-mono w-4 text-right shrink-0">
              {i + 1}
            </span>
            <div className="flex-1 min-w-0 flex items-center gap-1.5">
              <span className="text-text-pri truncate max-w-[4rem]">{it.name}</span>
              <div className="flex-1 h-3 rounded-sm overflow-hidden bg-white/5 flex items-center">
                <div
                  className={clsx('h-full', isUp ? 'bg-up' : 'bg-down')}
                  style={{ width: `${Math.max(wPct, 4)}%` }}
                />
              </div>
            </div>
            <span
              className={clsx(
                'font-mono shrink-0 min-w-[4rem] text-right',
                isUp ? 'text-up' : 'text-down',
              )}
            >
              {isUp ? '+' : ''}{it.netamountYi.toFixed(2)}亿
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ============ 占位 ============

function PlaceholderPanel({ label, note }: { label: string; note: string }) {
  return (
    <div className="bg-bg-subtle rounded-xl p-4 flex flex-col gap-2 min-h-[12rem]">
      <div className="text-xs text-text-ter uppercase tracking-wide font-medium">{label}</div>
      <div className="flex-1 flex items-center justify-center text-center">
        <div className="space-y-1">
          <div className="text-xs text-text-ter">{note}</div>
          <div className="text-[10px] text-text-ter">后续接入(SectorBoard 已存在)</div>
        </div>
      </div>
    </div>
  );
}