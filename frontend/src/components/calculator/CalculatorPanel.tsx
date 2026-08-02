'use client';

import { useCallback, useEffect, useState } from 'react';

import { Card } from '@/components/ui/Card';
import { PnlHeatmap } from '@/components/charts/PnlHeatmap';
import { decimalFormat } from '@/lib/decimalFormat';
import { apiGet, apiPost } from '@/lib/api';
import { normalizeCode } from '@/lib/stockCode';
import clsx from 'clsx';
import type {
  CalculatorBefore,
  CalculatorAfter,
  CalculatorResponse,
  Position,
  PositionListResponse,
} from '@/lib/types';

/**
 * 计算器主面板(ui-ux §4.2 + frontend-arch §10.2)
 *
 * 布局:左右分栏
 * - 左:持仓列表(可点击选中填入输入框;失败可重试)
 * - 右:输入 + 实时计算
 * 输入变化 → 自动调 POST /calculator → 显示新成本 + 21 档
 *
 * initialCode:从工作台传入的默认股票代码,弹窗打开时自动选中
 */
export function CalculatorPanel({
  initialCode = null,
}: {
  initialCode?: string | null;
}) {
  const [positions, setPositions] = useState<Position[]>([]);
  const [positionsError, setPositionsError] = useState<string | null>(null);
  const [positionsLoading, setPositionsLoading] = useState(true);
  const [stockCode, setStockCode] = useState(() => {
    const c = initialCode ? normalizeCode(initialCode) : null;
    return c ?? '000001.SZ';
  });
  const [action, setAction] = useState<'buy' | 'sell'>('buy');
  const [txShares, setTxShares] = useState(200);
  const [txPrice, setTxPrice] = useState('11.000');
  const [result, setResult] = useState<CalculatorResponse | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPositions = useCallback(async () => {
    setPositionsLoading(true);
    setPositionsError(null);
    try {
      const r = await apiGet<PositionListResponse>('/positions');
      setPositions(r.items);
    } catch (e) {
      const msg =
        e instanceof Error && e.message
          ? e.message
          : '持仓加载失败';
      setPositionsError(msg);
      setPositions([]);
    } finally {
      setPositionsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPositions();
  }, [loadPositions]);

  useEffect(() => {
    if (!initialCode) return;
    const c = normalizeCode(initialCode);
    if (c) setStockCode(c);
  }, [initialCode]);

  useEffect(() => {
    const norm = normalizeCode(stockCode);
    if (!norm) return;
    const pos = positions.find((p) => p.stockCode === norm);
    if (pos?.currentPrice != null) {
      setTxPrice(pos.currentPrice);
    }
  }, [stockCode, positions]);

  const currentPosition = positions.find(
    (p) => p.stockCode === normalizeCode(stockCode),
  );

  const currentPricePct =
    result?.after.costPrice != null && currentPosition?.currentPrice != null
      ? (Number(currentPosition.currentPrice) / Number(result.after.costPrice) - 1) * 100
      : undefined;

  // 实时计算(输入即算,300ms debounce)
  useEffect(() => {
    if (!txPrice || !stockCode || txShares <= 0) {
      setResult(null);
      return;
    }
    if (!/^\d+(\.\d{1,3})?$/.test(txPrice)) {
      setResult(null);
      return;
    }
    const handle = setTimeout(() => {
      doCalculate();
    }, 300);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stockCode, action, txShares, txPrice]);

  const doCalculate = async () => {
    setCalculating(true);
    setError(null);
    try {
      const resp = await apiPost<CalculatorResponse>('/calculator', {
        stockCode: normalizeCode(stockCode) ?? stockCode,
        action,
        txShares,
        txPrice,
      });
      setResult(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : '计算失败');
      setResult(null);
    } finally {
      setCalculating(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* 左:持仓列表 */}
      <Card padding="md">
        <h3 className="text-sm font-medium text-text-sec mb-3">当前持仓</h3>
        {positionsLoading ? (
          <p className="text-text-ter text-sm">加载中...</p>
        ) : positionsError ? (
          <div className="space-y-2">
            <p className="text-down text-sm">⚠ {positionsError}</p>
            <button
              onClick={loadPositions}
              className="text-xs px-3 py-1 rounded-sm bg-white/5 hover:bg-white/10 border border-white/10"
            >
              重试
            </button>
          </div>
        ) : positions.length === 0 ? (
          <p className="text-text-ter text-sm">暂无持仓(空仓建仓)</p>
        ) : (
          <ul className="space-y-1 max-h-64 overflow-y-auto pr-1">
            {positions.map((p) => {
              const selected = p.stockCode === normalizeCode(stockCode);
              const floating = p.floatingPnl != null ? Number(p.floatingPnl) : null;
              const floatingCls =
                floating == null
                  ? 'text-text-ter'
                  : floating > 0
                    ? 'text-up'
                    : floating < 0
                      ? 'text-down'
                      : 'text-text-ter';
              const cur = p.currentPrice != null ? Number(p.currentPrice) : null;
              const prev = p.prevClose != null ? Number(p.prevClose) : null;
              const priceCls =
                cur != null && prev != null && cur !== prev
                  ? cur > prev
                    ? 'text-up'
                    : 'text-down'
                  : 'text-text-sec';
              return (
                <li key={p.stockCode}>
                  <button
                    type="button"
                    onClick={() => setStockCode(p.stockCode)}
                    className={clsx(
                      'w-full text-left px-3 py-2 rounded-md transition-colors border',
                      selected
                        ? 'bg-accent-subtle border-accent/25'
                        : 'border-transparent hover:bg-white/5',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm truncate">
                        {p.stockName ?? p.stockCode}
                      </span>
                      <span className="text-text-ter text-xs font-mono shrink-0">
                        {p.stockCode}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-2 mt-1 text-xs">
                      <span className="text-text-sec">
                        {p.shares.toLocaleString()} 股 · 成本 ¥{p.avgCost} · 现价 ¥
                        <span className={clsx('font-mono', priceCls)}>
                          {p.currentPrice ?? '--'}
                        </span>
                      </span>
                      {floating != null && (
                        <span className={clsx('font-mono shrink-0', floatingCls)}>
                          {floating >= 0 ? '+' : ''}¥{floating.toFixed(2)}
                        </span>
                      )}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {/* 右:输入 + 实时结果 */}
      <Card padding="md">
        <h3 className="text-sm font-medium text-text-sec mb-3">预交易</h3>
        {positions.length === 0 ? (
          <p className="text-text-ter text-sm">暂无持仓,无法选择股票</p>
        ) : (
          <>
            <div className="text-xs text-text-sec mb-3">
              当前:
              <span className="ml-2 text-text-pri">
                {currentPosition?.stockName ?? stockCode}
              </span>
              <span className="ml-2 font-mono text-text-ter">{stockCode}</span>
            </div>

            <div className="space-y-3">
              <div className="flex gap-4 items-center">
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={action === 'buy'}
                    onChange={() => setAction('buy')}
                  />
                  <span className="text-down">买入</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={action === 'sell'}
                    onChange={() => setAction('sell')}
                  />
                  <span className="text-up">卖出</span>
                </label>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-text-ter mb-1.5">股数</label>
                  <input
                    type="number"
                    value={txShares}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setTxShares(v >= 1 ? v : 1);
                    }}
                    min={0}
                    step={100}
                    className="w-full px-3 py-2 border border-border-def rounded-md font-mono bg-bg-surface text-text-pri focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/30 transition-colors placeholder:text-text-ter/60"
                  />
                </div>
                <div>
                  <label className="block text-xs text-text-ter mb-1.5">成本价</label>
                  <input
                    type="text"
                    value={txPrice}
                    onChange={(e) => setTxPrice(e.target.value)}
                    placeholder="11.000"
                    className="w-full px-3 py-2 border border-border-def rounded-md font-mono bg-bg-surface text-text-pri focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/30 transition-colors placeholder:text-text-ter/60"
                  />
                </div>
              </div>

              <div className="text-xs text-text-ter">
                交易额 ¥{decimalFormat((txShares * Number(txPrice || 0)).toFixed(2))}
              </div>
            </div>

            {error && (
              <div className="mt-3 p-2 bg-up-bg text-up rounded-sm text-xs">
                {error}
              </div>
            )}
          </>
        )}
      </Card>

      {/* 实时结果 */}
      {result && (
        <Card padding="md" className="lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-text-sec">交易后(实时计算)</h3>
            {calculating && <span className="text-xs text-text-ter">计算中...</span>}
          </div>
          <ResultGrid before={result.before} after={result.after} />
          <PnlHeatmap grid={result.pnlGrid} currentPricePct={currentPricePct} />
        </Card>
      )}
    </div>
  );
}

function ResultGrid({ after }: { before: CalculatorBefore; after: CalculatorAfter }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
      <Stat label="新股数" value={`${after.shares.toLocaleString()} 股`} />
      <Stat
        label="新成本价"
        value={after.costPrice ? `¥${after.costPrice}` : '— 清仓'}
        highlight
      />
      <Stat label="持仓资金" value={`¥${decimalFormat(after.totalCost)}`} />
      <Stat
        label="已实现盈亏"
        value={`¥${decimalFormat(after.realizedPnl)}`}
        color={Number(after.realizedPnl) >= 0 ? 'up' : 'down'}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  highlight,
  color,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  color?: 'up' | 'down';
}) {
  return (
    <div className="bg-bg-subtle rounded-md p-3">
      <div className="text-xs text-text-ter mb-1">{label}</div>
      <div
        className={`font-mono font-semibold ${highlight ? 'text-accent' : ''} ${color === 'up' ? 'text-down' : color === 'down' ? 'text-up' : ''}`}
      >
        {value}
      </div>
    </div>
  );
}