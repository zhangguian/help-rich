'use client';

import { useCallback, useEffect, useState } from 'react';

import Link from 'next/link';

import { apiGet, apiPost } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { SkeletonState } from '@/components/ui/States';
import { pctClass } from '@/lib/format';
import {
  fetchWatchlistSummary,
  removeFromWatchlist,
  type PeriodBucket,
  type WatchlistSummary,
} from '@/lib/screener';

/** 比率(0.1234)→ 百分比文本;与 format.pct 入参语义不同,故不合并 */
function pctFmt(v: number | null | undefined): string {
  if (v == null) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(2)}%`;
}

export function WatchlistPanel() {
  const [data, setData] = useState<WatchlistSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const result = await fetchWatchlistSummary(refresh);
      setData(result);
    } catch (e: any) {
      setError(e?.message || '加载失败');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load(false);
  }, [load]);

  const handleRemove = useCallback(
    async (stockCode: string) => {
      try {
        await removeFromWatchlist(stockCode);
        // 本地移除
        setData((prev) => {
          if (!prev) return prev;
          const weeks = prev.weeks.map((w) => ({
            ...w,
            stocks: w.stocks.filter((s) => s.stockCode !== stockCode),
            stockCount: w.stocks.filter((s) => s.stockCode !== stockCode).length,
          }));
          const months = prev.months.map((m) => ({
            ...m,
            stocks: m.stocks.filter((s) => s.stockCode !== stockCode),
            stockCount: m.stocks.filter((s) => s.stockCode !== stockCode).length,
          }));
          return {
            ...prev,
            summary: { ...prev.summary, totalWatched: prev.summary.totalWatched - 1 },
            weeks,
            months,
          };
        });
      } catch (e: any) {
        // eslint-disable-next-line no-alert
        alert(`取消标记失败: ${e?.response?.data?.detail || e?.message}`);
      }
    },
    [],
  );

  if (loading) {
    return <SkeletonState rows={6} />;
  }
  if (error) {
    return (
      <Card className="p-6">
        <p className="text-red-500 font-medium">⚠ 加载失败</p>
        <p className="text-text-sec mt-2 text-sm">{error}</p>
        <Button variant="ghost" size="sm" onClick={() => load(false)} className="mt-4">
          🔄 重试
        </Button>
      </Card>
    );
  }
  if (!data || data.summary.totalWatched === 0) {
    return (
      <Card className="p-8 text-center">
        <p className="text-text-sec text-lg">⭐ 观察池为空</p>
        <p className="text-text-ter text-sm mt-2">
          去「📈 选股」tab,点击 Top20 卡片右上角 ⭐ 即可加入。
        </p>
        <p className="text-text-ter text-xs mt-1">
          加入后,每天会自动记录涨跌幅,可按周/月查看胜率。
        </p>
      </Card>
    );
  }

  const { summary, weeks, months } = data;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">⭐ 观察池 · 标选胜率</h1>
          <p className="text-text-sec mt-1 text-sm">
            共标选 <span className="text-text-pri font-mono">{summary.totalWatched}</span> 只 ·
            平均涨跌幅{' '}
            <span className={`font-mono ${pctClass(summary.overallAvgChange)}`}>
              {pctFmt(summary.overallAvgChange)}
            </span>{' '}
            · 胜率{' '}
            <span className="text-text-pri font-mono">
              {(summary.overallHitRate * 100).toFixed(1)}%
            </span>
          </p>
          {summary.todayCounted > 0 && (
            <p className="text-text-sec mt-1 text-sm">
              <span className="text-text-ter">今日({summary.todayDate})</span>{' '}
              <span className={`font-mono ${pctClass(summary.todayAvgChange)}`}>
                {pctFmt(summary.todayAvgChange)}
              </span>{' '}
              · hit{' '}
              <span className="text-up font-mono">{summary.todayHitCount}</span>{' '}
              / miss{' '}
              <span className="text-down font-mono">{summary.todayMissCount}</span>{' '}
              (计入 {summary.todayCounted} 只)
            </p>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => load(true)}
          disabled={refreshing}
          loading={refreshing}
        >
          🔄 刷新每日走势
        </Button>
      </div>

      {/* 周报表 */}
      <Card className="p-4">
        <h2 className="font-semibold mb-3">📅 按周分桶</h2>
        {weeks.length === 0 ? (
          <p className="text-text-sec text-sm">暂无周数据</p>
        ) : (
          <PeriodTable buckets={weeks} onRemove={handleRemove} />
        )}
      </Card>

      {/* 月报表 */}
      <Card className="p-4">
        <h2 className="font-semibold mb-3">🗓 按月分桶</h2>
        {months.length === 0 ? (
          <p className="text-text-sec text-sm">暂无月数据</p>
        ) : (
          <PeriodTable buckets={months} onRemove={handleRemove} />
        )}
      </Card>

      <p className="text-text-ter text-xs">
        刷新时间: {summary.refreshedAt ? new Date(summary.refreshedAt).toLocaleString('zh-CN') : '—'}
      </p>
    </div>
  );
}

/** 周/月通用表格 */
function PeriodTable({
  buckets,
  onRemove,
}: {
  buckets: PeriodBucket[];
  onRemove: (stockCode: string) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-text-ter border-b border-border-def">
            <th className="text-left py-2 pr-3">周期</th>
            <th className="text-right py-2 px-3">股数</th>
            <th className="text-right py-2 px-3">平均涨跌</th>
            <th className="text-right py-2 px-3">hit / miss</th>
            <th className="text-right py-2 px-3">胜率</th>
            <th className="text-left py-2 pl-3">个股</th>
          </tr>
        </thead>
        <tbody>
          {buckets.map((b) => (
            <tr key={b.label} className="border-b border-border-def/40 hover:bg-bg-subtle/30">
              <td className="py-2 pr-3">
                <div className="font-mono">{b.label}</div>
                <div className="text-xs text-text-ter">
                  {b.start} ~ {b.end}
                </div>
              </td>
              <td className="text-right py-2 px-3 font-mono">{b.stockCount}</td>
              <td className={`text-right py-2 px-3 font-mono ${pctClass(b.avgChangePct)}`}>
                {pctFmt(b.avgChangePct)}
              </td>
              <td className="text-right py-2 px-3 font-mono">
                <span className="text-up">{b.hitCount}</span>
                {' / '}
                <span className="text-down">{b.missCount}</span>
              </td>
              <td className="text-right py-2 px-3 font-mono">
                {(b.hitRate * 100).toFixed(1)}%
              </td>
              <td className="py-2 pl-3">
                <div className="flex flex-wrap gap-1.5">
                  {b.stocks.map((s) => (
                    <span
                      key={s.watchlistId}
                      className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded border ${
                        s.latestPctFromMarked != null && s.latestPctFromMarked > 0
                          ? 'border-up/30 bg-up/10'
                          : s.latestPctFromMarked != null && s.latestPctFromMarked < 0
                          ? 'border-down/30 bg-down/10'
                          : 'border-border-def bg-bg-subtle'
                      }`}
                    >
                      <Link
                        href={`/stock/${encodeURIComponent(s.stockCode)}`}
                        className="font-mono hover:text-accent"
                      >
                        {s.stockCode}
                      </Link>
                      <span className={pctClass(s.latestPctFromMarked)}>
                        {pctFmt(s.latestPctFromMarked)}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          if (confirm(`确认从观察池移除 ${s.stockName}(${s.stockCode})?`)) {
                            onRemove(s.stockCode);
                          }
                        }}
                        title="取消标记"
                        className="text-text-ter hover:text-red-500 ml-1"
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}