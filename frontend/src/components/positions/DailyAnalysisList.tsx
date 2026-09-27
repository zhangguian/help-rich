'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { apiGet } from '@/lib/api';
import type { DailyAnalysisItem, DailyAnalysisList as DailyAnalysisListResp } from '@/lib/types';

import { Card } from '@/components/ui/Card';

const HORIZON = 20;

/**
 * 每日 AI 分析历史列表
 *
 * - 每条:日期 + 综合分 + view + N 天后实际涨跌(命中/反向/数据不足) + 评语展开
 * - 顶部下拉选择 5/10/30/60/90 天窗口
 */
export function DailyAnalysisList({ stockCode }: { stockCode: string }) {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<DailyAnalysisListResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (!stockCode) return;
    setLoading(true);
    setError(null);
    try {
      const r = await apiGet<DailyAnalysisListResp>(
        `/diagnose/stock/${encodeURIComponent(stockCode)}/daily-analyses?days=${days}&horizon=${HORIZON}`,
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

  return (
    <Card padding="md" className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold">📅 历史分析</div>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="px-2 py-1 text-xs rounded-lg bg-bg-subtle border border-border-def text-text-pri"
        >
          {[7, 14, 30, 60, 90].map((d) => (
            <option key={d} value={d}>
              最近 {d} 天
            </option>
          ))}
        </select>
      </div>

      {loading && <div className="text-xs text-text-ter">⏳ 加载中…</div>}

      {error && <div className="text-xs text-down">⚠ {error}</div>}

      {!loading && !error && data && data.items.length === 0 && (
        <div className="text-xs text-text-ter text-center py-6 bg-bg-subtle rounded-lg">
          暂无分析记录 — 在首页对 {stockCode} 点「开始分析」即可生成
        </div>
      )}

      {!loading && !error && data && data.items.length > 0 && (
        <div className="space-y-2">
          {data.items.map((it) => (
            <DailyAnalysisRow key={it.createdAt + it.analysisDate} item={it} />
          ))}
        </div>
      )}
    </Card>
  );
}

function DailyAnalysisRow({ item }: { item: DailyAnalysisItem }) {
  const [expanded, setExpanded] = useState(false);

  const viewMeta =
    item.aiView === 'bullish'
      ? { label: '看多', emoji: '📈', cls: 'text-up bg-up-bg' }
      : item.aiView === 'bearish'
        ? { label: '看空', emoji: '📉', cls: 'text-down bg-down-bg' }
        : { label: '中性', emoji: '➖', cls: 'text-text-sec bg-bg-subtle' };

  const outcomeMeta =
    item.outcome === 'hit'
      ? { label: '命中', cls: 'text-up' }
      : item.outcome === 'miss'
        ? { label: '反向', cls: 'text-down' }
        : { label: '数据不足', cls: 'text-text-ter' };

  return (
    <div className="border border-border-def rounded-lg p-3 space-y-2">
      {/* 第一行:日期 + view + 综合分 + N 天后涨跌 */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 text-xs">
          <span className="font-mono text-text-pri">{item.analysisDate}</span>
          <span
            className={clsx(
              'px-2 py-0.5 rounded text-xs font-medium border',
              viewMeta.cls,
            )}
          >
            {viewMeta.emoji} {viewMeta.label}
          </span>
          {item.scoreAvg != null && (
            <span className="text-text-sec">
              分 <span className="font-mono text-text-pri">{item.scoreAvg}</span>
            </span>
          )}
        </div>
        <div className={clsx('flex items-center gap-1 text-xs', outcomeMeta.cls)}>
          <span className="font-medium">{outcomeMeta.label}</span>
          {item.actualChangePct && (
            <span className="font-mono">({item.actualChangePct}%)</span>
          )}
        </div>
      </div>

      {/* 评语展开 */}
      {item.aiSummary && (
        <div>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-xs text-text-ter hover:text-text-sec"
          >
            {expanded ? '▾ 收起评语' : '▸ 展开评语'}
          </button>
          {expanded && (
            <div className="mt-2 text-xs text-text-sec leading-relaxed whitespace-pre-wrap border-t border-border-def pt-2">
              {item.aiSummary}
            </div>
          )}
        </div>
      )}
    </div>
  );
}