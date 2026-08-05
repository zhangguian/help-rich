'use client';

import { useState } from 'react';

import clsx from 'clsx';

import { apiGet, apiPost } from '@/lib/api';
import { useUIStore } from '@/stores/useUIStore';
import type { ReplaySummary, ReplayWindow } from '@/lib/types';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';

const WINDOWS: { key: ReplayWindow; label: string }[] = [
  { key: '1d', label: '1 日' },
  { key: '3d', label: '3 日' },
  { key: '5d', label: '1 周' },
  { key: '10d', label: '2 周' },
  { key: '20d', label: '4 周' },
  { key: '60d', label: '1 季度' },
];

/** 五维度色阶:<10 红 / 10~15 黄 / >=15 绿 */
function dimColor(score: number) {
  if (score >= 15) return 'bg-up';
  if (score >= 10) return 'bg-warn';
  return 'bg-down';
}

/**
 * 一键复盘卡片(v2.3)
 *
 * - 顶部 6 窗口按钮(默认 1d);切换触发新请求
 * - 5 维度条形图 + Top 3 问题
 * - AI 评语 + 失败/缺 Key 降级提示
 * - 右上有「🔄 重算」按钮(强制调 LLM)
 */
export function ReplayCard({
  stockCode,
  initial,
}: {
  stockCode: string;
  initial: ReplaySummary | null;
}) {
  const showToast = useUIStore((s) => s.showToast);
  const [data, setData] = useState<ReplaySummary | null>(initial);
  const [window, setWindow] = useState<ReplayWindow>('1d');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

  const fetchOne = async (w: ReplayWindow) => {
    setLoading(true);
    setError(null);
    const t0 = Date.now();
    try {
      const r = await apiGet<ReplaySummary>(
        `/diagnose/stock/${encodeURIComponent(stockCode)}/summary?window=${w}`,
        { timeout: 30000 },
      );
      setData(r);
      setElapsed(Date.now() - t0);
    } catch (e) {
      // REPLAY_NOT_FOUND = 该窗口尚未复盘,属正常空态:清空 data 显示空态而非错误
      const code = (e as { code?: string })?.code;
      if (code === 'REPLAY_NOT_FOUND') {
        setData(null);
      } else if (e instanceof Error) {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  };

  const switchWindow = async (w: ReplayWindow) => {
    setWindow(w);
    await fetchOne(w);
  };

  const forceReplay = async () => {
    setLoading(true);
    setError(null);
    const t0 = Date.now();
    try {
      // 60s:LLM 调用典型 5~15s,加上 summarize K 线 / LLM 重试可能更长
      const r = await apiPost<ReplaySummary>(
        `/diagnose/stock/${encodeURIComponent(stockCode)}/summary?window=${window}`,
        undefined,
        { timeout: 60000 },
      );
      setData(r);
      setElapsed(Date.now() - t0);
      showToast({ type: 'success', message: '复盘已更新' });
    } catch (e) {
      if (e instanceof Error) setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card padding="md" className="space-y-3">
      {/* 顶部:窗口选择 + 重算 */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-1.5 flex-wrap">
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              onClick={() => void switchWindow(w.key)}
              disabled={loading}
              className={clsx(
                'px-3 py-1 text-xs rounded-lg transition-colors',
                window === w.key
                  ? 'bg-accent-subtle text-accent border border-accent/30'
                  : 'bg-white/5 text-text-sec hover:text-text-pri border border-white/5',
              )}
            >
              {w.label}
            </button>
          ))}
        </div>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => void forceReplay()}
          loading={loading}
          title="强制重新计算(跳过 24h 缓存)"
        >
          🔄 一键复盘
        </Button>
      </div>

      {loading && (
        <div className="text-xs text-text-ter">
          ⏳ 复盘中… {elapsed != null ? `(${elapsed}ms)` : ''}
        </div>
      )}

      {error && (
        <div className="text-xs text-down">⚠ {error}</div>
      )}

      {/* 空态:该窗口尚未复盘 */}
      {!loading && !error && !data && (
        <div className="text-xs text-text-ter text-center py-4">
          该窗口暂无复盘记录,点右上「🔄 一键复盘」生成
        </div>
      )}

      {!loading && !error && data && (
        <>
          {/* 5 维度条形图 */}
          <div className="space-y-1.5">
            <div className="text-xs text-text-sec mb-1">
              5 维度均值 · 综合分{' '}
              <span className="font-mono text-text-pri">
                {data.scoreAvg ?? '—'}
              </span>
              {data.aiLatencyMs != null && (
                <span className="text-text-ter ml-2">
                  ({data.aiLatencyMs}ms)
                </span>
              )}
            </div>
            {Object.entries(data.dimensionAvg).map(([dim, score]) => (
              <div key={dim} className="flex items-center gap-2 text-xs">
                <span className="w-24 shrink-0 text-text-sec">{dim}</span>
                <div className="flex-1 h-2 bg-white/5 rounded-full overflow-hidden">
                  <div
                    className={clsx('h-full transition-all', dimColor(score))}
                    style={{ width: `${Math.min(100, (score / 20) * 100)}%` }}
                  />
                </div>
                <span className="font-mono text-text-pri w-10 text-right">
                  {score.toFixed(1)}
                </span>
              </div>
            ))}
          </div>

          {/* Top 3 问题 */}
          {data.topIssues.length > 0 && (
            <div className="space-y-1 border-t border-white/10 pt-2">
              <div className="text-xs text-text-sec">Top 3 问题(低分优先)</div>
              {data.topIssues.map((it, idx) => (
                <div key={idx} className="flex items-start gap-2 text-xs">
                  <span className="text-down">⚠</span>
                  <span className="font-mono text-text-pri w-16 shrink-0">
                    {it.dim} {it.score}分
                  </span>
                  <span className="text-text-ter">{it.hint}</span>
                </div>
              ))}
            </div>
          )}

          {/* AI 评语 */}
          <div className="border-t border-white/10 pt-2">
            {data.aiStatus === 'no_key' && (
              <div className="text-xs text-warn">
                ⚠ LLM 未配置 Key — 请到「设置」页填写
              </div>
            )}
            {data.aiStatus === 'failed' && (
              <div className="text-xs text-down">
                ⚠ LLM 调用失败 — 可稍后重试
              </div>
            )}
            {data.aiStatus === 'success' && data.aiComment && (
              <div className="text-xs text-text-sec leading-relaxed whitespace-pre-wrap">
                {data.aiComment}
              </div>
            )}
          </div>

          {/* 流水概要 */}
          <div className="text-xs text-text-ter border-t border-white/10 pt-2">
            窗口内 {data.summarySnapshot.txCount} 笔流水
            (买 {data.summarySnapshot.buyCount} / 卖 {data.summarySnapshot.sellCount})
            · 已实现盈亏 ¥{data.summarySnapshot.realizedPnl}
            · 持仓占比 {data.summarySnapshot.concentrationPct}%
            {data.summarySnapshot.isInWatchlist && ' · ⭐ 自选'}
          </div>
        </>
      )}
    </Card>
  );
}