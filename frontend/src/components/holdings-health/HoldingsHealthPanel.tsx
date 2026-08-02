'use client';

import { useEffect, useState } from 'react';

import { apiGet } from '@/lib/api';
import { decimalFormat } from '@/lib/decimalFormat';
import type { HoldingsHealth } from '@/lib/types';

import { Card } from '@/components/ui/Card';
import { SkeletonState } from '@/components/ui/States';
import { TermHint } from '@/components/ui/TermHint';

/**
 * 持仓体检面板(v0.4.0,弹窗内)
 *
 * 从真实持仓主数据出发 + 实时行情,输出:
 * - 组合:总市值 / 总浮盈 / 盈亏率 / 风险等级
 * - 单只:现价 / 浮盈 / 盈亏率 / 集中度 / 状态(健康/浮亏/高集中)
 */
const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  profit: { text: '盈利', cls: 'text-up' },
  loss: { text: '浮亏', cls: 'text-down' },
  flat: { text: '持平', cls: 'text-text-sec' },
  high_concentration: { text: '高集中', cls: 'text-warn' },
  unknown: { text: '无行情', cls: 'text-text-ter' },
};

export function HoldingsHealthPanel() {
  const [data, setData] = useState<HoldingsHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiGet<HoldingsHealth>('/holdings-health')
      .then(setData)
      .catch((e) => setError(e?.response?.data?.detail?.message ?? '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const riskCls =
    data?.riskLevel === '高'
      ? 'text-up'
      : data?.riskLevel === '中'
        ? 'text-warn'
        : 'text-down';

  if (loading) return <SkeletonState rows={3} height="h-16" />;

  if (error) {
    return (
      <Card padding="md">
        <p className="text-down">⚠ {error}</p>
      </Card>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-4">
      {data.quotesUnavailable && (
        <Card padding="md" className="border-warn">
          <p className="text-warn text-sm">
            ⚠ 部分股票行情获取失败,已按成本价降级显示(浮盈记为 0)
          </p>
        </Card>
      )}

      {/* 组合总览 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1 inline-flex items-center">
            持仓数<TermHint term="position_count" />
          </div>
          <div className="text-2xl font-mono font-semibold">{data.totalPositions}</div>
        </Card>
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1 inline-flex items-center">
            总市值<TermHint term="total_market_value" />
          </div>
          <div className="text-2xl font-mono font-semibold">
            ¥{decimalFormat(data.totalMarketValue)}
          </div>
        </Card>
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1 inline-flex items-center">
            总浮盈<TermHint term="total_floating_pnl" />
          </div>
          <div
            className={`text-2xl font-mono font-semibold ${
              Number(data.totalFloatingPnl) >= 0 ? 'text-up' : 'text-down'
            }`}
          >
            {Number(data.totalFloatingPnl) >= 0 ? '+' : ''}¥
            {decimalFormat(data.totalFloatingPnl)}
          </div>
          <div className="text-xs text-text-ter mt-1 inline-flex items-center">
            盈亏率<TermHint term="pnl_ratio" /> {data.pnlRatioPct >= 0 ? '+' : ''}
            {data.pnlRatioPct}%
          </div>
        </Card>
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1 inline-flex items-center">
            风险等级<TermHint term="risk_level" />
          </div>
          <div className={`text-2xl font-mono font-semibold ${riskCls}`}>
            {data.riskLevel}
          </div>
          <div className="text-xs text-text-ter mt-1 inline-flex items-center">
            {data.riskScore > 0 ? (
              <>
                风险分<TermHint term="risk_score" /> {data.riskScore}
              </>
            ) : (
              '无持仓'
            )}
          </div>
        </Card>
      </div>

      {/* 风险警告 */}
      {data.warnings.length > 0 && (
        <Card padding="md" className="border-warn">
          <h3 className="font-semibold mb-2 text-warn">⚠ 风险提示</h3>
          <ul className="space-y-1">
            {data.warnings.map((w, i) => (
              <li key={i} className="text-sm text-text-sec">
                · {w}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* 单只持仓 */}
      {data.items.length === 0 ? (
        <Card padding="lg">
          <p className="text-center text-text-ter py-8">
            暂无持仓,可在首页导入持仓后回来体检
          </p>
        </Card>
      ) : (
        <div className="space-y-3">
          {data.items.map((p) => {
            const st =
              STATUS_LABEL[p.status] ?? { text: '未知', cls: 'text-text-ter' };
            return (
              <Card key={p.stockCode} padding="md">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold truncate">
                      {p.stockName ?? p.stockCode}
                      <span className="text-text-ter text-sm ml-2 font-mono">
                        {p.stockCode}
                      </span>
                      <span
                        className={`ml-2 text-xs ${st.cls} inline-flex items-center`}
                      >
                        {st.text}
                        <TermHint
                          term={
                            p.status === 'profit'
                              ? 'status_profit'
                              : p.status === 'loss'
                                ? 'status_loss'
                                : p.status === 'flat'
                                  ? 'status_flat'
                                  : p.status === 'high_concentration'
                                    ? 'status_high_concentration'
                                    : 'status_no_quote'
                          }
                        />
                      </span>
                    </div>
                    <div className="text-sm text-text-sec mt-1">
                      {p.shares} 股 · 成本 ¥{decimalFormat(p.avgCost)} · 现价 ¥
                      {decimalFormat(p.currentPrice)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div
                      className={`font-mono font-semibold ${
                        Number(p.floatingPnl) >= 0 ? 'text-up' : 'text-down'
                      }`}
                    >
                      {Number(p.floatingPnl) >= 0 ? '+' : ''}¥
                      {decimalFormat(p.floatingPnl)}
                    </div>
                    <div className="text-xs text-text-ter mt-1 inline-flex items-center">
                      {p.floatingPnlRatioPct >= 0 ? '+' : ''}
                      {p.floatingPnlRatioPct}% · 占比<TermHint term="concentration" /> {p.concentrationPct}%
                    </div>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
