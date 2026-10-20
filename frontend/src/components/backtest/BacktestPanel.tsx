'use client';

import { useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import {
  compareWeightsBacktest,
  fetchWeights,
  runSignalBacktest,
  type BacktestResult,
  type CompareWeightsResult,
} from '@/lib/api/advanced';

/** 两种回测模式 —— 前视偏差是这里最关键的差异,必须在 UI 上说清 */
type Mode = 'signal' | 'compare';

const METRIC_LABELS: Array<{ key: string; label: string; suffix?: string; tone?: boolean }> = [
  { key: 'total_return_pct', label: '总收益', suffix: '%', tone: true },
  { key: 'annual_return_pct', label: '年化收益', suffix: '%', tone: true },
  { key: 'max_drawdown_pct', label: '最大回撤', suffix: '%' },
  { key: 'volatility_pct', label: '年化波动', suffix: '%' },
  { key: 'sharpe', label: '夏普' },
  { key: 'win_rate_pct', label: '胜率', suffix: '%' },
  { key: 'profit_loss_ratio', label: '盈亏比' },
  { key: 'trade_count', label: '交易次数' },
];

function fmt(v: unknown, suffix = ''): string {
  if (v == null) return '—';
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n)) return '—';
  return `${n.toFixed(2)}${suffix}`;
}

/**
 * 策略回测(阶段2)
 *
 * 界面上明确区分「无前视偏差」与「有前视偏差」两种模式,
 * 因为含偏差的回测结果好看但不可信 —— 不标清楚用户会拿它做真实决策。
 */
export function BacktestPanel() {
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [compare, setCompare] = useState<CompareWeightsResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [days, setDays] = useState(120);
  const [capital, setCapital] = useState(100000);
  const [mode, setMode] = useState<Mode>('signal');

  const run = async () => {
    setLoading(true);
    setError('');
    setResult(null);
    setCompare(null);
    try {
      const range = { days, initial_capital: capital };

      if (mode === 'signal') {
        setResult(await runSignalBacktest(range));
      } else {
        // 校准:对比"当前生效权重"与"等权基准",看调参到底改变什么
        const view = await fetchWeights();
        const current: Record<string, number> = {};
        const equal: Record<string, number> = {};
        for (const f of view.factors) {
          current[f.key] = f.enabled ? f.weight : 0;
          equal[f.key] = 50; // 各因子同分,作为中性基准
        }

        const r = await compareWeightsBacktest({
          ...range,
          weight_sets: [
            { label: '当前权重', weights: current },
            { label: '等权基准', weights: equal },
          ],
        });
        setCompare(r);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '回测失败');
    } finally {
      setLoading(false);
    }
  };

  const metrics = result?.metrics ?? {};

  return (
    <div className="space-y-4">
      <Card padding="lg" className="space-y-3">
        <header>
          <h2 className="text-base font-semibold">策略回测</h2>
        </header>

        <div className="grid gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => setMode('signal')}
            className={clsx(
              'rounded-md border p-2.5 text-left transition',
              mode === 'signal'
                ? 'border-accent bg-accent/10'
                : 'border-border-base hover:bg-bg-elev',
            )}
          >
            <div className="flex items-center gap-1.5 text-sm font-medium">
              信号回测
              <span className="rounded bg-success/15 px-1.5 py-0.5 text-[10px] text-success">
                无前视偏差
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-text-ter">
              用历史每日选股结果当买入信号,衡量选股逻辑真实表现
            </p>
          </button>

          <button
            type="button"
            onClick={() => setMode('compare')}
            className={clsx(
              'rounded-md border p-2.5 text-left transition',
              mode === 'compare'
                ? 'border-accent bg-accent/10'
                : 'border-border-base hover:bg-bg-elev',
            )}
          >
            <div className="flex items-center gap-1.5 text-sm font-medium">
              权重校准
              <span className="rounded bg-danger/15 px-1.5 py-0.5 text-[10px] text-danger">
                含前视偏差
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-text-ter">
              用当前权重重算历史,观察权重敏感度 —— 仅供理解,不可当真实收益
            </p>
          </button>
        </div>

        {mode === 'compare' && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-[11px] text-danger">
            注意:该模式用「今天的权重」去回算「历史某天该选哪些股」,
            而当天你并不知道这套权重。结果会系统性偏乐观,**不能作为策略收益预期**。
            真实校准需要先改权重、再等新信号积累足量样本后重新做信号回测。
          </div>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1 text-[11px]">
            <span className="text-text-ter">回看天数</span>
            <input
              type="number"
              min={20}
              max={720}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="w-24 rounded-md border border-border-base bg-bg-elev px-2 py-1.5 text-xs text-text-pri"
            />
          </label>
          <label className="space-y-1 text-[11px]">
            <span className="text-text-ter">初始资金</span>
            <input
              type="number"
              min={10000}
              step={10000}
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
              className="w-32 rounded-md border border-border-base bg-bg-elev px-2 py-1.5 text-xs text-text-pri"
            />
          </label>
          <button
            type="button"
            onClick={() => void run()}
            disabled={loading}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-bg-base transition hover:opacity-90 disabled:opacity-50"
          >
            {loading ? '回测中…' : mode === 'signal' ? '开始回测' : '开始校准对比'}
          </button>
        </div>

        {error && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}
      </Card>

      {compare && (
        <>
          {!compare.ok ? (
            <Card padding="lg">
              <p className="text-sm text-text-ter">{compare.reason ?? '无法完成对比'}</p>
            </Card>
          ) : (
            <Card padding="lg" className="space-y-3">
              <header className="space-y-1">
                <h3 className="text-sm font-semibold">权重敏感度</h3>
                <p className="text-[11px] text-text-ter">{compare.note}</p>
              </header>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-left text-text-ter">
                    <tr>
                      <th className="py-1">权重方案</th>
                      <th className="py-1 text-right">总收益</th>
                      <th className="py-1 text-right">最大回撤</th>
                      <th className="py-1 text-right">交易数</th>
                      <th className="py-1">入选标的</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(compare.results ?? {}).map(([label, r]) => {
                      const m = r.metrics ?? {};
                      const ret = Number(m.total_return_pct ?? 0);
                      return (
                        <tr key={label} className="border-t border-border-base">
                          <td className="py-1.5 font-medium">{label}</td>
                          <td
                            className={clsx(
                              'py-1.5 text-right font-mono',
                              ret >= 0 ? 'text-danger' : 'text-success',
                            )}
                          >
                            {fmt(m.total_return_pct, '%')}
                          </td>
                          <td className="py-1.5 text-right font-mono">
                            {fmt(m.max_drawdown_pct, '%')}
                          </td>
                          <td className="py-1.5 text-right">{fmt(m.trade_count)}</td>
                          <td className="py-1.5 font-mono text-[11px] text-text-sec">
                            {(r.selectedCodes ?? []).join(', ') || '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {compare.weightsSensitive === false && (
                <p className="rounded-md border border-border-base bg-bg-elev/40 px-3 py-2 text-[11px] text-text-ter">
                  两套权重在所选区间内选出了完全相同的股票 —— 说明当前区间上权重对结果不敏感。
                  这不代表权重无用,而是需要更长的历史或更大的权重差异才能观察到区别。
                </p>
              )}
            </Card>
          )}
        </>
      )}

      {result && (
        <>
          {result.warnings && result.warnings.length > 0 && (
            <Card padding="md" className="space-y-1">
              {result.warnings.map((w, i) => (
                <p key={i} className="text-[11px] text-warning">
                  ⚠️ {w}
                </p>
              ))}
            </Card>
          )}

          <Card padding="lg" className="space-y-3">
            <h3 className="text-sm font-semibold">绩效指标</h3>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {METRIC_LABELS.map((m) => {
                const raw = metrics[m.key];
                const num = typeof raw === 'number' ? raw : Number(raw);
                const positive = Number.isFinite(num) && num >= 0;
                return (
                  <div key={m.key} className="rounded-md border border-border-base p-2.5">
                    <dt className="text-[11px] text-text-ter">{m.label}</dt>
                    <dd
                      className={clsx(
                        'mt-0.5 font-mono text-sm',
                        m.tone && (positive ? 'text-danger' : 'text-success'),
                      )}
                    >
                      {fmt(raw, m.suffix ?? '')}
                    </dd>
                  </div>
                );
              })}
            </dl>
            {result.has_lookahead_bias && (
              <p className="text-[11px] text-danger">
                ⚠️ 本次结果包含前视偏差,不可当作真实收益参考
              </p>
            )}
          </Card>

          {result.equity_curve && result.equity_curve.length > 1 && (
            <Card padding="lg" className="space-y-2">
              <h3 className="text-sm font-semibold">净值曲线</h3>
              {(() => {
                const curve = result.equity_curve!;
                const values = curve.map((p) => p.equity);
                const min = Math.min(...values);
                const max = Math.max(...values);
                const span = max - min || 1;
                const first = values[0] ?? min;
                const lastPoint = curve[curve.length - 1];
                return (
                  <>
                    <div className="flex items-end gap-[2px]" style={{ height: 96 }}>
                      {values.map((v, i) => (
                        <div
                          key={i}
                          className={clsx(
                            'flex-1 rounded-sm',
                            v >= first ? 'bg-danger/70' : 'bg-success/70',
                          )}
                          style={{ height: `${Math.max(4, ((v - min) / span) * 96)}px` }}
                          title={`${curve[i]?.date ?? ''} · ${v.toFixed(2)}`}
                        />
                      ))}
                    </div>
                    <div className="flex justify-between font-mono text-[10px] text-text-ter">
                      <span>{curve[0]?.date ?? ''}</span>
                      <span>{lastPoint?.date ?? ''}</span>
                    </div>
                  </>
                );
              })()}
            </Card>
          )}

          {result.trades && result.trades.length > 0 && (
            <Card padding="lg" className="space-y-2">
              <h3 className="text-sm font-semibold">成交明细({result.trades.length})</h3>
              <div className="max-h-72 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-bg-base text-left text-text-ter">
                    <tr>
                      <th className="py-1">日期</th>
                      <th className="py-1">方向</th>
                      <th className="py-1">代码</th>
                      <th className="py-1">股数</th>
                      <th className="py-1">价格</th>
                      <th className="py-1 text-right">盈亏</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => {
                      const action = String(t.action ?? '');
                      const pnl = t.pnl as number | null | undefined;
                      return (
                        <tr key={i} className="border-t border-border-base">
                          <td className="py-1 font-mono">{String(t.date ?? '')}</td>
                          <td className="py-1">
                            <span
                              className={clsx(
                                action === 'buy' ? 'text-danger' : 'text-success',
                              )}
                            >
                              {action === 'buy' ? '买入' : '卖出'}
                            </span>
                          </td>
                          <td className="py-1 font-mono">{String(t.stock_code ?? '')}</td>
                          <td className="py-1">{String(t.shares ?? '')}</td>
                          <td className="py-1 font-mono">{String(t.price ?? '')}</td>
                          <td
                            className={clsx(
                              'py-1 text-right font-mono',
                              pnl == null
                                ? 'text-text-ter'
                                : pnl >= 0
                                  ? 'text-danger'
                                  : 'text-success',
                            )}
                          >
                            {pnl == null ? '—' : `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
