'use client';

import { useCallback, useEffect, useState } from 'react';

import Link from 'next/link';
import { useParams } from 'next/navigation';

import { AnalysisPanel } from '@/components/advice/AnalysisPanel';
import { IntradayChart } from '@/components/charts/IntradayChart';
import { KLineChart } from '@/components/charts/KLineChart';
import { WinrateCard } from '@/components/positions/WinrateCard';
import { DailyAnalysisList } from '@/components/positions/DailyAnalysisList';
import { Card } from '@/components/ui/Card';
import { EtfBadge } from '@/components/ui/EtfBadge';
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
 *
 * ⚠️ **为什么这里要有日 K 图**:本页原本只有**分时图**,而四类异动行为标注
 * (主力异动 / 低吸 / 锁仓 / 高抛)是**日线级别**的形态标注 —— 画在分时图上
 * 根本不成立。于是「找股页看到信号 → 点进个股页在图上找得到」这条闭环是断的
 * (找股页跳这里,但这里没有带标注的 K 线)。
 * 复用盯盘页同一个 `KLineChart`(它已合并 signalSeries + behaviorMarkers 并按
 * time 排序),不新造图表组件、不新造样式。
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
        <h1 className="font-mono text-2xl font-semibold text-text-pri mt-2">
          {stockCode}
          {/* 场内 ETF 品种徽章(跨境/商品类带 T+0) */}
          <EtfBadge code={stockCode} className="ml-2 align-middle" />
        </h1>
        <p className="text-xs text-text-ter mt-1">个股详情 · 技术分析 / 胜率 / 历史复盘</p>
      </header>

      {loading && <SkeletonState rows={6} />}

      {!loading && error && <ErrorState message={error} onRetry={load} />}

      {!loading && !error && (
        <>
          {/* ⚠️ 分时图:必须显式给 height。
              IntradayChart 默认 height=420,此前这里只给 Card 写了 h-[320px] ——
              卡片压不住 420px 的图,分时图**溢出 150px 压在下一张卡上**
              (下方内容被图表的时间轴/成交量标签糊住)。
              现在让卡片按内容撑开,图表高度显式写死,不再溢出。 */}
          <Card padding="md">
            <IntradayChart stockCode={stockCode} height={280} />
          </Card>

          {/* 日 K(带四类异动行为标注)—— 找股页点进来的落点就在这里 */}
          <Card padding="md">
            <p className="text-xs text-text-ter mb-2">
              日K · 异动行为标注(主力异动 / 低吸 / 锁仓 / 高抛,悬停看当日依据)
            </p>
            <KLineChart stockCode={stockCode} period="daily" height={420} />
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
