'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import {
  fetchPaperAccounts,
  fetchPaperOrders,
  fetchPaperSummary,
  paperBuy,
  paperSell,
  type PaperAccount,
  type PaperOrderRow,
  type PaperSummary,
} from '@/lib/api/advanced';

/**
 * 模拟盘面板(阶段3)
 *
 * 明确提示用户:这是模拟盘,不碰真实持仓。
 * 买入/卖出的价格由后端取实时行情,**前端不给价格输入框** ——
 * 允许手填价格就变成了"虚构成交价",模拟结果毫无参考价值。
 */
export function PaperTradingPanel() {
  const [accounts, setAccounts] = useState<PaperAccount[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [summary, setSummary] = useState<PaperSummary | null>(null);
  const [orders, setOrders] = useState<PaperOrderRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const [code, setCode] = useState('');
  const [shares, setShares] = useState(100);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchPaperAccounts();
      const list = data.items ?? [];
      setAccounts(list);
      setActiveId((prev) => prev ?? list[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (id: number) => {
    try {
      const [s, o] = await Promise.all([
        fetchPaperSummary(id),
        fetchPaperOrders(id),
      ]);
      setSummary(s);
      setOrders(o.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载明细失败');
    }
  }, []);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  useEffect(() => {
    if (activeId != null) void loadDetail(activeId);
  }, [activeId, loadDetail]);

  const trade = async (action: 'buy' | 'sell') => {
    if (activeId == null) return;
    if (!code.trim()) {
      setError('请填写股票代码');
      return;
    }
    setBusy(true);
    setError('');
    try {
      if (action === 'buy') {
        await paperBuy(activeId, code.trim().toUpperCase(), shares);
      } else {
        await paperSell(activeId, code.trim().toUpperCase(), shares);
      }
      setCode('');
      await loadDetail(activeId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '下单失败');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <Card padding="lg">
        <div className="text-sm text-text-sec">加载模拟账户中…</div>
      </Card>
    );
  }

  if (accounts.length === 0) {
    return (
      <Card padding="lg">
        <div className="text-sm text-text-ter">
          还没有模拟账户。调用 <code className="font-mono">POST /api/paper-trading/accounts</code>{' '}
          创建后即可使用。
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </div>
      )}

      {summary && (
        <Card padding="lg" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-base font-semibold">{summary.name}</h2>
              <p className="mt-1 text-xs text-text-ter">
                模拟盘 · 与真实持仓完全隔离
              </p>
            </div>
            <select
              value={activeId ?? ''}
              onChange={(e) => setActiveId(Number(e.target.value))}
              className="rounded-md border border-border-def bg-bg-elevated px-2 py-1 text-xs text-text-pri"
              aria-label="选择模拟账户"
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>

          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: '总资产', value: summary.totalEquity.toFixed(2) },
              { label: '可用现金', value: Number(summary.cash).toFixed(2) },
              { label: '持仓市值', value: summary.marketValue.toFixed(2) },
              {
                label: '总收益率',
                value: `${summary.totalReturnPct >= 0 ? '+' : ''}${summary.totalReturnPct.toFixed(2)}%`,
                tone: summary.totalReturnPct >= 0 ? 'up' : 'down',
              },
            ].map((item) => (
              <div key={item.label} className="rounded-md border border-border-def p-2.5">
                <dt className="text-[11px] text-text-ter">{item.label}</dt>
                <dd
                  className={clsx(
                    'mt-0.5 font-mono text-sm',
                    item.tone === 'up' && 'text-danger',
                    item.tone === 'down' && 'text-success',
                  )}
                >
                  {item.value}
                </dd>
              </div>
            ))}
          </dl>

          <div className="flex flex-wrap items-end gap-2">
            <label className="space-y-1 text-[11px]">
              <span className="text-text-ter">股票代码</span>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="600519.SH"
                className="w-40 rounded-md border border-border-def bg-bg-elevated px-2 py-1.5 text-xs text-text-pri outline-none focus:border-accent"
              />
            </label>
            <label className="space-y-1 text-[11px]">
              <span className="text-text-ter">股数(100 的倍数)</span>
              <input
                type="number"
                step={100}
                min={100}
                value={shares}
                onChange={(e) => setShares(Number(e.target.value))}
                className="w-32 rounded-md border border-border-def bg-bg-elevated px-2 py-1.5 text-xs text-text-pri"
              />
            </label>
            <button
              type="button"
              onClick={() => void trade('buy')}
              disabled={busy}
              className="rounded-md bg-danger px-3 py-1.5 text-xs font-medium text-white transition hover:opacity-90 disabled:opacity-50"
            >
              模拟买入
            </button>
            <button
              type="button"
              onClick={() => void trade('sell')}
              disabled={busy}
              className="rounded-md bg-success px-3 py-1.5 text-xs font-medium text-white transition hover:opacity-90 disabled:opacity-50"
            >
              模拟卖出
            </button>
            <span className="text-[11px] text-text-ter">成交价取实时行情,不可手填</span>
          </div>
        </Card>
      )}

      {summary && summary.positions.length > 0 && (
        <Card padding="lg" className="space-y-2">
          <h3 className="text-sm font-semibold">模拟持仓</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-text-ter">
                <tr>
                  <th className="py-1">代码</th>
                  <th className="py-1">股数</th>
                  <th className="py-1">成本</th>
                  <th className="py-1">现价</th>
                  <th className="py-1 text-right">浮动盈亏</th>
                </tr>
              </thead>
              <tbody>
                {summary.positions.map((p) => (
                  <tr key={p.stockCode} className="border-t border-border-def">
                    <td className="py-1.5 font-mono">{p.stockCode}</td>
                    <td className="py-1.5">{p.shares}</td>
                    <td className="py-1.5 font-mono">{p.avgCost}</td>
                    <td className="py-1.5 font-mono">{p.currentPrice}</td>
                    <td
                      className={clsx(
                        'py-1.5 text-right font-mono',
                        p.unrealizedPnl >= 0 ? 'text-danger' : 'text-success',
                      )}
                    >
                      {p.unrealizedPnl >= 0 ? '+' : ''}
                      {p.unrealizedPnl.toFixed(2)}({p.unrealizedPct.toFixed(2)}%)
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card padding="lg" className="space-y-2">
        <h3 className="text-sm font-semibold">模拟流水</h3>
        {orders.length === 0 ? (
          <div className="text-xs text-text-ter">还没有模拟成交</div>
        ) : (
          <ul className="divide-y divide-border-def text-xs">
            {orders.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center gap-2 py-1.5">
                <span
                  className={clsx(
                    'rounded px-1.5 py-0.5 text-[10px]',
                    o.action === 'buy' ? 'bg-danger/15 text-danger' : 'bg-success/15 text-success',
                  )}
                >
                  {o.action === 'buy' ? '买入' : '卖出'}
                </span>
                <span className="font-mono">{o.stockCode}</span>
                <span className="text-text-sec">
                  {o.shares} 股 @ {o.price}
                </span>
                <span className="text-text-ter">费用 {o.fee}</span>
                <span className="ml-auto font-mono text-text-ter">{o.tradeDate}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
