'use client';

import { useEffect, useState } from 'react';

import { Card } from '@/components/ui/Card';
import { PnlHeatmap } from '@/components/charts/PnlHeatmap';
import { decimalFormat } from '@/lib/decimalFormat';
import { apiGet, apiPost } from '@/lib/api';
import { normalizeCode } from '@/lib/stockCode';
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
 * - 左:当前持仓(实时拉 GET /positions)
 * - 右:输入 + 实时计算
 * 输入变化 → 自动调 POST /calculator → 显示新成本 + 21 档
 */
export function CalculatorPanel() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [stockCode, setStockCode] = useState('000001');
  const [action, setAction] = useState<'buy' | 'sell'>('buy');
  const [txShares, setTxShares] = useState(500);
  const [txPrice, setTxPrice] = useState('11.000');
  const [result, setResult] = useState<CalculatorResponse | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 拉当前持仓(只一次)
  useEffect(() => {
    let cancelled = false;
    apiGet<PositionListResponse>('/positions')
      .then((r) => {
        if (!cancelled) setPositions(r.items);
      })
      .catch(() => {
        // 忽略,允许空持仓
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const currentPosition = positions.find((p) => p.stockCode === normalizeCode(stockCode));

  // 实时计算(输入即算,300ms debounce)
  useEffect(() => {
    if (!txPrice || !stockCode || txShares <= 0) {
      setResult(null);
      return;
    }
    // 价格格式校验(允许数字 + 最多 3 位小数)
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
      {/* 左:当前持仓 */}
      <Card padding="md">
        <h3 className="text-sm font-medium text-text-sec mb-3">当前持仓</h3>
        {currentPosition ? (
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-text-ter text-sm">股票</span>
              <span>
                {currentPosition.stockName ?? currentPosition.stockCode}
                <span className="text-text-ter text-xs ml-2 font-mono">
                  {currentPosition.stockCode}
                </span>
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-ter text-sm">持仓</span>
              <span className="font-mono">
                {currentPosition.shares.toLocaleString()} 股
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-ter text-sm">加权成本</span>
              <span className="font-mono">¥{currentPosition.avgCost}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-ter text-sm">总成本</span>
              <span className="font-mono">
                ¥{decimalFormat(currentPosition.totalCost)}
              </span>
            </div>
          </div>
        ) : (
          <p className="text-text-ter text-sm">无此股票持仓(空仓建仓)</p>
        )}
      </Card>

      {/* 右:输入 + 实时结果 */}
      <Card padding="md">
        <h3 className="text-sm font-medium text-text-sec mb-3">预交易</h3>
        <div className="space-y-3">
          <div className="flex gap-2">
            <input
              type="text"
              value={stockCode}
              onChange={(e) => setStockCode(e.target.value)}
              maxLength={12}
              placeholder="600519 或 600519.SH"
              className="flex-1 px-3 py-2 border border-border-strong rounded-sm font-mono"
            />
          </div>

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

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs text-text-ter mb-1">股数</label>
              <input
                type="number"
                value={txShares}
                onChange={(e) => setTxShares(Number(e.target.value))}
                min={1}
                step={100}
                className="w-full px-3 py-2 border border-border-strong rounded-sm font-mono"
              />
            </div>
            <div>
              <label className="block text-xs text-text-ter mb-1">价格</label>
              <input
                type="text"
                value={txPrice}
                onChange={(e) => setTxPrice(e.target.value)}
                placeholder="11.000"
                className="w-full px-3 py-2 border border-border-strong rounded-sm font-mono"
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
      </Card>

      {/* 实时结果 */}
      {result && (
        <Card padding="md" className="lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-text-sec">交易后(实时计算)</h3>
            {calculating && <span className="text-xs text-text-ter">计算中...</span>}
          </div>
          <ResultGrid before={result.before} after={result.after} />
          <PnlHeatmap grid={result.pnlGrid} />
        </Card>
      )}
    </div>
  );
}

function ResultGrid({ before, after }: { before: CalculatorBefore; after: CalculatorAfter }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
      <Stat label="新股数" value={`${after.shares.toLocaleString()} 股`} />
      <Stat
        label="新成本价"
        value={after.costPrice ? `¥${after.costPrice}` : '— 清仓'}
        highlight
      />
      <Stat label="新总成本" value={`¥${decimalFormat(after.totalCost)}`} />
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