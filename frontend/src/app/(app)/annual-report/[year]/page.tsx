'use client';

import { useState } from 'react';

import Link from 'next/link';

import { useEffect } from 'react';

import { apiGet } from '@/lib/api';
import { decimalFormat } from '@/lib/decimalFormat';

import { Card } from '@/components/ui/Card';
import { SkeletonState } from '@/components/ui/States';

/**
 * 年账单数据(P6.2)
 */
interface AnnualReportData {
  year: number;
  realizedProfit: string;
  realizedLoss: string;
  netPnl: string;
  closedCount: number;
  winRate: number;
  noTransactions?: boolean;
  top5Profit: Array<{
    stockCode: string;
    stockName: string | null;
    realizedPnl: string;
    tradeDate: string;
  }>;
  top5Loss: Array<{
    stockCode: string;
    stockName: string | null;
    realizedPnl: string;
    tradeDate: string;
  }>;
  // GB-001 IR-4:费用双口径
  realizedProfitGross: string | null;
  realizedLossGross: string | null;
  netPnlGross: string | null;
  totalFee: string | null;
  feesEnabled: boolean;
  // GB-001 IR-5
  closedCycles: number;
  tNetContribution: string | null;
  trendNetPnl: string | null;
  dietzReturn: string | null;
}

const MONTHS = [
  '一月', '二月', '三月', '四月', '五月', '六月',
  '七月', '八月', '九月', '十月', '十一月', '十二月',
];

export default function AnnualReportPage({
  params,
}: {
  params: { year: string };
}) {
  const year = parseInt(params.year, 10);
  const [data, setData] = useState<AnnualReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (Number.isNaN(year)) return;
    setLoading(true);
    setError(null);
    apiGet<AnnualReportData>(`/annual-report/${year}`)
      .then(setData)
      .catch((e) => setError(e?.response?.data?.detail?.message ?? '加载失败'))
      .finally(() => setLoading(false));
  }, [year]);

  if (Number.isNaN(year)) {
    return (
      <main className="min-h-screen p-8 max-w-4xl mx-auto">
        <p className="text-up">年份无效</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-8 max-w-4xl mx-auto space-y-6">
      <header>
        <Link href="/" className="text-sm text-text-sec hover:text-text-pri">
          ← 返回首页
        </Link>
        <h1 className="text-2xl font-bold mt-2">{year} 年度账单</h1>
        <p className="text-text-sec text-sm mt-1">
          {MONTHS[0]} ~ {MONTHS[11]} 已实现盈亏 + 胜率 + Top5
        </p>
      </header>

      {loading && <SkeletonState rows={3} height="h-16" />}

      {error && (
        <Card padding="md">
          <p className="text-up">⚠ {error}</p>
        </Card>
      )}

      {data && !loading && (
        <>
          {/* v0.4.0:无流水提示(持仓可直接导入,不强制有流水) */}
          {data.noTransactions && (
            <Card padding="md" className="border-warn">
              <p className="text-warn text-sm">
                ⚠ {year} 年还没有交易流水。年账单基于流水计算;若只想管理持仓,
                可直接在首页通过「截图识别 → 粘贴持仓 JSON」或「+ 添加持仓」导入。
              </p>
            </Card>
          )}

          {/* 4 宫格总览 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card padding="md">
              <div className="text-text-sec text-sm mb-1">
                已实现盈亏
                {data.feesEnabled && (
                  <span className="text-[11px] text-text-ter ml-1">(含费)</span>
                )}
              </div>
              <div
                className={`text-2xl font-mono font-semibold ${
                  Number(data.netPnl) >= 0 ? 'text-up' : 'text-down'
                }`}
              >
                {Number(data.netPnl) >= 0 ? '+' : ''}¥
                {decimalFormat(data.netPnl)}
              </div>
              {data.feesEnabled && data.netPnlGross != null && (
                <div className="text-xs text-text-ter mt-1">
                  不含费 ¥{decimalFormat(data.netPnlGross)}
                  {data.totalFee != null && (
                    <span> · 费用 ¥{decimalFormat(data.totalFee)}</span>
                  )}
                </div>
              )}
            </Card>
            <Card padding="md">
              <div className="text-text-sec text-sm mb-1">已实现盈利</div>
              <div className="text-2xl font-mono font-semibold text-up">
                ¥{decimalFormat(data.realizedProfit)}
              </div>
            </Card>
            <Card padding="md">
              <div className="text-text-sec text-sm mb-1">已实现亏损</div>
              <div className="text-2xl font-mono font-semibold text-down">
                ¥{decimalFormat(data.realizedLoss)}
              </div>
            </Card>
            <Card padding="md">
              <div className="text-text-sec text-sm mb-1">胜率</div>
              <div className="text-2xl font-mono font-semibold">
                {(data.winRate * 100).toFixed(0)}%
              </div>
              <div className="text-xs text-text-ter mt-1">
                平仓周期 {data.closedCycles} 个
                {data.closedCount > data.closedCycles &&
                  ` · 卖出笔数 ${data.closedCount}`}
              </div>
            </Card>
          </div>

          {/* GB-001 IR-5:做 T 归因 + 时间加权收益率 */}
          {data.tNetContribution != null && (
            <Card padding="md">
              <h3 className="font-semibold mb-3">🧬 收益归因(GB-001 IR-5)</h3>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <div>
                  <div className="text-xs text-text-ter mb-1">做 T 净贡献</div>
                  <div
                    className={`font-mono text-lg font-semibold ${
                      Number(data.tNetContribution) >= 0 ? 'text-up' : 'text-down'
                    }`}
                  >
                    {Number(data.tNetContribution) >= 0 ? '+' : ''}¥
                    {decimalFormat(data.tNetContribution)}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-text-ter mb-1">趋势持仓净贡献</div>
                  <div
                    className={`font-mono text-lg font-semibold ${
                      Number(data.trendNetPnl) >= 0 ? 'text-up' : 'text-down'
                    }`}
                  >
                    {Number(data.trendNetPnl) >= 0 ? '+' : ''}¥
                    {decimalFormat(data.trendNetPnl)}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-text-ter mb-1">
                    资金加权收益率(modified Dietz)
                  </div>
                  <div
                    className={`font-mono text-lg font-semibold ${
                      Number(data.dietzReturn) >= 0 ? 'text-up' : 'text-down'
                    }`}
                  >
                    {data.dietzReturn != null
                      ? `${(Number(data.dietzReturn) * 100).toFixed(2)}%`
                      : '—'}
                  </div>
                </div>
              </div>
              <p className="text-xs text-text-ter mt-3">
                做 T = 同股 3 日内反向交易。胜率按「建仓→清仓」平仓周期聚合,
                避免高频小赢虚增胜率。
              </p>
            </Card>
          )}

          {/* Top 5 最赚 + 最亏 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card padding="md">
              <h3 className="font-semibold mb-3 text-up">🏆 Top 5 最赚</h3>
              {data.top5Profit.length === 0 ? (
                <p className="text-text-ter text-sm">无盈利记录</p>
              ) : (
                <table className="w-full text-sm">
                  <tbody>
                    {data.top5Profit.map((t, i) => (
                      <tr key={i} className="border-t border-border-def">
                        <td className="py-2">
                          <span className="font-mono text-xs text-text-ter mr-2">
                            #{i + 1}
                          </span>
                          {t.stockName ?? t.stockCode}
                        </td>
                        <td className="py-2 text-right font-mono text-up font-semibold">
                          +¥{decimalFormat(t.realizedPnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
            <Card padding="md">
              <h3 className="font-semibold mb-3 text-down">💔 Top 5 最亏</h3>
              {data.top5Loss.length === 0 ? (
                <p className="text-text-ter text-sm">无亏损记录</p>
              ) : (
                <table className="w-full text-sm">
                  <tbody>
                    {data.top5Loss.map((t, i) => (
                      <tr key={i} className="border-t border-border-def">
                        <td className="py-2">
                          <span className="font-mono text-xs text-text-ter mr-2">
                            #{i + 1}
                          </span>
                          {t.stockName ?? t.stockCode}
                        </td>
                        <td className="py-2 text-right font-mono text-down font-semibold">
                          ¥{decimalFormat(t.realizedPnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>
        </>
      )}
    </main>
  );
}