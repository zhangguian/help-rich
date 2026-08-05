'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { apiGet } from '@/lib/api';
import type { WinrateResponse } from '@/lib/types';

import { Card } from '@/components/ui/Card';

const WINDOWS: { key: number; label: string }[] = [
  { key: 5, label: '5 日' },
  { key: 10, label: '10 日' },
  { key: 30, label: '30 日' },
  { key: 60, label: '60 日' },
  { key: 90, label: '90 日' },
];

const HORIZON = 20;  // N 天后判定窗口

/**
 * 顶部胜率卡
 *
 * - 5/10/30/60/90 天窗口选择
 * - 显示 overall_accuracy + bullish/bearish 分方向胜率
 * - insufficient 时显示"样本不足"提示
 * - 📈 同向模拟:勾选后显示"若按 AI 建议等权 1 单位操作"的累计简单收益率
 */
export function WinrateCard({ stockCode }: { stockCode: string }) {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<WinrateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [simulate, setSimulate] = useState(false);

  const fetch = useCallback(async () => {
    if (!stockCode) return;
    setLoading(true);
    setError(null);
    try {
      const r = await apiGet<WinrateResponse>(
        `/diagnose/stock/${encodeURIComponent(stockCode)}/daily-analyses/winrate?days=${days}&horizon=${HORIZON}`,
        { timeout: 30000 },
      );
      setData(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : '拉取失败');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [stockCode, days]);

  useEffect(() => {
    void fetch();
  }, [fetch]);

  const acc = data?.overallAccuracy;
  const accCls =
    acc == null
      ? 'text-text-ter'
      : acc >= 0.6
        ? 'text-up'
        : acc >= 0.4
          ? 'text-warn'
          : 'text-down';

  return (
    <Card padding="md" className="space-y-3">
      {/* 顶部:窗口选择 */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-sm font-semibold">📊 分析胜率(view vs {HORIZON} 日后)</div>
        <div className="flex items-center gap-1.5">
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              onClick={() => setDays(w.key)}
              disabled={loading}
              className={clsx(
                'px-3 py-1 text-xs rounded-lg transition-colors',
                days === w.key
                  ? 'bg-accent-subtle text-accent border border-accent/30'
                  : 'bg-white/5 text-text-sec hover:text-text-pri border border-white/5',
              )}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="text-xs text-text-ter">⏳ 计算中…</div>
      )}

      {error && (
        <div className="text-xs text-down">⚠ {error}</div>
      )}

      {!loading && !error && data && (
        <>
          {data.insufficient ? (
            <div className="text-xs text-text-ter text-center py-3 bg-bg-subtle rounded-lg">
              样本不足({data.samples} &lt; 3),无法给出结论 — 多积累几周分析后再看
            </div>
          ) : (
            <>
              {/* 综合准确率 */}
              <div className="flex items-baseline gap-2">
                <span className="text-xs text-text-sec">综合准确率</span>
                <span className={clsx('text-2xl font-mono font-semibold', accCls)}>
                  {acc == null ? '—' : `${(acc * 100).toFixed(1)}%`}
                </span>
                <span className="text-xs text-text-ter">
                  ({data.samples} 样本 · 跳过 {data.skipped})
                </span>
              </div>

              {/* 分方向胜率 */}
              <div className="grid grid-cols-2 gap-3 pt-2">
                <DirectionBar
                  label="看多"
                  emoji="📈"
                  data={data.bullish}
                />
                <DirectionBar
                  label="看空"
                  emoji="📉"
                  data={data.bearish}
                />
              </div>

              {/* 同向模拟 */}
              <div className="flex items-center justify-between gap-2 pt-2 border-t border-white/5">
                <label className="flex items-center gap-1.5 text-xs text-text-sec cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={simulate}
                    onChange={(e) => setSimulate(e.target.checked)}
                    className="accent-accent size-3.5"
                  />
                  📈 同向模拟
                </label>
                {simulate && (
                  <div className="text-xs text-text-ter">
                    若按 AI 建议操作累计{' '}
                    <span
                      className={clsx(
                        'font-mono font-semibold',
                        data.simulateReturnPct == null
                          ? 'text-text-ter'
                          : data.simulateReturnPct >= 0
                            ? 'text-up'
                            : 'text-down',
                      )}
                    >
                      {data.simulateReturnPct == null
                        ? '样本不足'
                        : `${data.simulateReturnPct >= 0 ? '+' : ''}${data.simulateReturnPct.toFixed(2)}%`}
                    </span>
                    <span className="text-text-ter"> 等权1单位/次</span>
                  </div>
                )}
              </div>

              <div className="text-xs text-text-ter pt-1">
                生成于 {data.generatedAt}
              </div>
            </>
          )}
        </>
      )}
    </Card>
  );
}

function DirectionBar({
  label,
  emoji,
  data,
}: {
  label: string;
  emoji: string;
  data: { total: number; hits: number; winrate: number | null };
}) {
  const wr = data.winrate;
  const wrPct = wr == null ? '—' : `${(wr * 100).toFixed(1)}%`;
  const barW = wr == null ? 0 : Math.round(wr * 100);
  const barCls =
    wr == null ? 'bg-text-ter' : wr >= 0.6 ? 'bg-up' : wr >= 0.4 ? 'bg-warn' : 'bg-down';
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-text-sec">
          {emoji} {label}
        </span>
        <span className="font-mono text-text-pri">{wrPct}</span>
      </div>
      <div className="flex-1 h-2 bg-white/5 rounded-full overflow-hidden">
        <div
          className={clsx('h-full transition-all', barCls)}
          style={{ width: `${barW}%` }}
        />
      </div>
      <div className="text-xs text-text-ter text-right">
        {data.hits}/{data.total} 命中
      </div>
    </div>
  );
}