'use client';

import { useEffect, useState } from 'react';

import Link from 'next/link';

import { apiGet } from '@/lib/api';
import { decimalFormat } from '@/lib/decimalFormat';

import { Card } from '@/components/ui/Card';
import { SkeletonState } from '@/components/ui/States';

/**
 * 风险敞口报告(C1)
 *
 * 指标:
 * - 总持仓 + 总市值
 * - 单股集中度 + HHI 指数
 * - 板块分散度
 * - 风险评分(0~100,中/低/高)+ 警告
 *
 * 字段命名 camelCase:axios 响应拦截器自动把 snake_case → camelCase
 */
interface RiskReport {
  totalPositions: number;
  totalMarketValue: number;
  singleStockConcentration: Record<string, number>;
  topHoldingRatio: number;
  hhiIndex: number;
  sectorBreakdown: Record<string, number>;
  sectorCount: number;
  riskScore: number;
  riskLevel: '低' | '中' | '高';
  warnings: string[];
}

const RISK_COLOR: Record<string, string> = {
  低: 'text-down',
  中: 'text-warn',
  高: 'text-up',
};

const RISK_BG: Record<string, string> = {
  低: 'bg-down-bg',
  中: 'bg-warn-bg',
  高: 'bg-up-bg',
};

export default function RiskReportPage() {
  const [data, setData] = useState<RiskReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<RiskReport>('/risk-report')
      .then(setData)
      .catch((e) => setError(e?.response?.data?.detail?.message ?? '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="min-h-screen p-8 max-w-4xl mx-auto space-y-6">
      <header>
        <Link href="/" className="text-sm text-text-sec hover:text-text-pri">
          ← 返回首页
        </Link>
        <h1 className="text-2xl font-bold mt-2">风险敞口报告</h1>
        <p className="text-text-sec text-sm mt-1">
          基于当前持仓计算集中度 + 板块分散度 + 风险评分
        </p>
      </header>

      {loading && <SkeletonState rows={3} height="h-20" />}

      {error && (
        <Card padding="md">
          <p className="text-up">⚠ {error}</p>
        </Card>
      )}

      {data && !loading && (
        <>
          {/* 4 宫格 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card padding="md">
              <div className="text-text-sec text-sm mb-1">总持仓数</div>
              <div className="text-2xl font-mono font-semibold">
                {data.totalPositions}
              </div>
            </Card>
            <Card padding="md">
              <div className="text-text-sec text-sm mb-1">总市值</div>
              <div className="text-2xl font-mono font-semibold">
                ¥{decimalFormat(data.totalMarketValue)}
              </div>
            </Card>
            <Card padding="md">
              <div className="text-text-sec text-sm mb-1">HHI 指数</div>
              <div className="text-2xl font-mono font-semibold">
                {data.hhiIndex.toFixed(0)}
              </div>
              <div className="text-xs text-text-ter mt-1">&lt;2500 健康</div>
            </Card>
            <Card padding="md" className={RISK_BG[data.riskLevel]}>
              <div className="text-text-sec text-sm mb-1">风险评分</div>
              <div className={`text-2xl font-mono font-semibold ${RISK_COLOR[data.riskLevel]}`}>
                {data.riskScore} / 100
              </div>
              <div className={`text-xs mt-1 font-semibold ${RISK_COLOR[data.riskLevel]}`}>
                风险等级:{data.riskLevel}
              </div>
            </Card>
          </div>

          {/* 警告 */}
          {data.warnings.length > 0 && (
            <Card padding="md">
              <h3 className="font-semibold mb-3">⚠ 风险提示</h3>
              <ul className="space-y-1.5 text-sm">
                {data.warnings.map((w, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-warn">•</span>
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* 单股集中度 + 板块分布 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card padding="md">
              <h3 className="font-semibold mb-3">单股集中度</h3>
              <div className="space-y-2">
                {Object.entries(data.singleStockConcentration)
                  .sort(([, a], [, b]) => b - a)
                  .map(([code, pct]) => (
                    <div key={code}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="font-mono">{code}</span>
                        <span className="font-mono tabular-nums">
                          {pct.toFixed(1)}%
                        </span>
                      </div>
                      <div className="h-2 rounded-sm bg-bg-subtle overflow-hidden">
                        <div
                          className={
                            pct >= 30
                              ? 'h-full bg-up'
                              : pct >= 15
                                ? 'h-full bg-warn'
                                : 'h-full bg-down'
                          }
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  ))}
              </div>
            </Card>
            <Card padding="md">
              <h3 className="font-semibold mb-3">板块分布</h3>
              {data.sectorCount === 0 ? (
                <p className="text-text-ter text-sm">无数据</p>
              ) : (
                <div className="space-y-2">
                  {Object.entries(data.sectorBreakdown)
                    .sort(([, a], [, b]) => b - a)
                    .map(([sec, pct]) => (
                      <div key={sec}>
                        <div className="flex justify-between text-xs mb-1">
                          <span>{sec}</span>
                          <span className="font-mono tabular-nums">
                            {pct.toFixed(1)}%
                          </span>
                        </div>
                        <div className="h-2 rounded-sm bg-bg-subtle overflow-hidden">
                          <div
                            className="h-full bg-accent"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    ))}
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </main>
  );
}