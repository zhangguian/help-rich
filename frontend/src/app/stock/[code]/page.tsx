'use client';

import { useCallback, useEffect, useState } from 'react';

import Link from 'next/link';
import { useParams } from 'next/navigation';

import { AnalysisPanel } from '@/components/advice/AnalysisPanel';
import { IntradayChart } from '@/components/charts/IntradayChart';
import { WinrateCard } from '@/components/positions/WinrateCard';
import { DailyAnalysisList } from '@/components/positions/DailyAnalysisList';
import { Card } from '@/components/ui/Card';
import { ErrorState, SkeletonState } from '@/components/ui/States';
import { apiGet } from '@/lib/api';
import type { AnalysisResult } from '@/lib/types';

/**
 * 个股详情页 — /stock/[code]
 *
 * 复用既有个股视图(AnalysisPanel / IntradayChart / WinrateCard / DailyAnalysisList),
 * 不新造布局。本页解决 ScreenerPanel 与 WatchlistPanel 中 3 处指向该路由的断链。
 *
 * 说明:本页只读展示既有分析结果,不触发 SSE 流式分析(那是首页盯盘页的职责),
 * 因此不传 aiProgress,刷新走普通 GET。
 */
export default function StockDetailPage() {
  const params = useParams<{ code: string }>();
  const stockCode = decodeURIComponent(params.code ?? '');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!stockCode) return;
    setLoading(true);
    setError(null);
    apiGet<AnalysisResult>(`/stock/${encodeURIComponent(stockCode)}/analysis`)
      .then(setAnalysis)
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : '分析数据加载失败');
      })
      .finally(() => setLoading(false));
  }, [stockCode]);

  useEffect(load, [load]);

  if (!stockCode) {
    return (
      <main className="min-h-screen p-8 max-w-6xl mx-auto">
        <ErrorState message="缺少股票代码参数" onRetry={() => window.location.reload()} />
      </main>
    );
  }

  return (
    <main className="min-h-screen p-8 max-w-6xl mx-auto space-y-6">
      <header>
        <Link href="/" className="text-sm text-text-ter hover:text-accent">
          ← 返回盯盘
        </Link>
        <h1 className="font-mono text-2xl font-semibold text-text-pri mt-2">{stockCode}</h1>
        <p className="text-xs text-text-ter mt-1">个股详情 · 技术分析 / 胜率 / 历史复盘</p>
      </header>

      {loading && <SkeletonState rows={6} />}

      {!loading && error && <ErrorState message={error} onRetry={load} />}

      {!loading && !error && (
        <>
          <Card padding="md" className="h-[320px]">
            <IntradayChart stockCode={stockCode} />
          </Card>

          <AnalysisPanel
            analysis={analysis}
            started={false}
            loading={false}
            onRefresh={load}
            onRetry={load}
          />

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            <WinrateCard stockCode={stockCode} />
            <DailyAnalysisList stockCode={stockCode} />
          </div>
        </>
      )}
    </main>
  );
}
