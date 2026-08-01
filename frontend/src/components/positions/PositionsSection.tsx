'use client';

import { useCallback, useEffect, useState } from 'react';

import Link from 'next/link';

import { apiDelete, apiGet, apiPost } from '@/lib/api';
import { decimalFormat } from '@/lib/decimalFormat';
import type { Position, PositionListResponse } from '@/lib/types';
import { useUIStore } from '@/stores/useUIStore';

import { PositionsList } from './PositionsList';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';

/** 全局事件:截图导入持仓 / 流水变动后触发,刷新持仓区 */
export const POSITIONS_UPDATED_EVENT = 'positions-updated';

export function refreshPositions() {
  window.dispatchEvent(new CustomEvent(POSITIONS_UPDATED_EVENT));
}

/**
 * 首页持仓区(v0.4.0 client 化)
 *
 * - 总览 4 宫格 + 持仓列表(删除 / 添加)
 * - 监听 POSITIONS_UPDATED_EVENT:截图导入持仓后自动刷新
 */
export function PositionsSection() {
  const showToast = useUIStore((s) => s.showToast);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);

  const fetchPositions = useCallback(async () => {
    try {
      const resp = await apiGet<PositionListResponse>('/positions');
      setPositions(resp.items);
    } catch {
      /* toast 已由拦截器处理 */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPositions();
    window.addEventListener(POSITIONS_UPDATED_EVENT, fetchPositions);
    return () => window.removeEventListener(POSITIONS_UPDATED_EVENT, fetchPositions);
  }, [fetchPositions]);

  const onDelete = async (p: Position) => {
    if (!window.confirm(`删除持仓 ${p.stockName ?? p.stockCode}?将同时删除该股全部流水`)) return;
    try {
      await apiDelete(`/positions/${p.stockCode}`);
      showToast({ type: 'success', message: '已删除持仓' });
      fetchPositions();
    } catch {
      /* toast 已由拦截器处理 */
    }
  };

  const onAdd = async (form: { stockCode: string; shares: number; costPrice: string; stockName?: string }) => {
    try {
      await apiPost('/positions', form);
      showToast({ type: 'success', message: '持仓已保存' });
      setShowAdd(false);
      fetchPositions();
      return true;
    } catch {
      return false;
    }
  };

  const totalCost = positions.reduce((sum, p) => sum + Number(p.totalCost), 0);
  const floatingPnl = positions.reduce((sum, p) => sum + Number(p.floatingPnl ?? 0), 0);
  const todayPnl = positions.reduce((sum, p) => sum + Number(p.todayPnl ?? 0), 0);
  const hasQuotes = positions.some((p) => p.currentPrice !== null);

  const pnlClass = (v: number) => (v >= 0 ? 'text-up' : 'text-down');

  return (
    <>
      {/* 总览(P3.5.2:4 宫格) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1">总成本</div>
          <div className="text-2xl font-mono font-semibold">
            ¥{decimalFormat(totalCost.toFixed(2))}
          </div>
        </Card>
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1">总浮盈</div>
          <div className={`text-2xl font-mono font-semibold ${pnlClass(floatingPnl)}`}>
            {hasQuotes ? `¥${decimalFormat(floatingPnl.toFixed(2))}` : '--'}
          </div>
          <div className="text-xs text-text-ter mt-1">
            {hasQuotes ? '现价 - 加权成本' : '行情暂不可用'}
          </div>
        </Card>
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1">今日盈亏</div>
          <div className={`text-2xl font-mono font-semibold ${pnlClass(todayPnl)}`}>
            {hasQuotes ? `¥${decimalFormat(todayPnl.toFixed(2))}` : '--'}
          </div>
          <div className="text-xs text-text-ter mt-1">
            {hasQuotes ? '现价 - 昨收' : '行情暂不可用'}
          </div>
        </Card>
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1">持仓数</div>
          <div className="text-2xl font-mono font-semibold">{positions.length}</div>
        </Card>
      </div>

      {/* 持仓列表 */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">我的持仓</h2>
        <div className="flex gap-2">
          <Link href="/holdings-health">
            <Button size="sm" variant="ghost">
              🩺 持仓体检
            </Button>
          </Link>
          <Button size="sm" variant="secondary" onClick={() => setShowAdd((v) => !v)}>
            + 添加持仓
          </Button>
        </div>
      </div>

      {showAdd && (
        <AddPositionForm
          onCancel={() => setShowAdd(false)}
          onAdd={onAdd}
        />
      )}

      {loading ? (
        <Card padding="lg">
          <p className="text-text-ter text-sm">加载中…</p>
        </Card>
      ) : positions.length === 0 ? (
        <Card padding="lg">
          <div className="text-center py-8">
            <p className="text-text-ter mb-2">还没有持仓记录</p>
            <p className="text-xs text-text-ter mb-4">
              v0.4.0:持仓可直接导入 —— 在下方"截图识别"粘贴持仓 JSON,或手动添加
            </p>
            <div className="flex justify-center gap-2">
              <Button variant="primary" onClick={() => setShowAdd(true)}>
                + 添加持仓
              </Button>
              <Link href="/transactions">
                <Button variant="secondary">📋 录入流水</Button>
              </Link>
            </div>
          </div>
        </Card>
      ) : (
        <PositionsList positions={positions} onDelete={onDelete} />
      )}
    </>
  );
}

function AddPositionForm({
  onCancel,
  onAdd,
}: {
  onCancel: () => void;
  onAdd: (form: {
    stockCode: string;
    shares: number;
    costPrice: string;
    stockName?: string;
  }) => Promise<boolean>;
}) {
  const [stockCode, setStockCode] = useState('');
  const [stockName, setStockName] = useState('');
  const [shares, setShares] = useState('');
  const [costPrice, setCostPrice] = useState('');
  const [busy, setBusy] = useState(false);
  const showToast = useUIStore((s) => s.showToast);

  const submit = async () => {
    const sharesNum = Number(shares);
    const price = costPrice.trim();
    if (!stockCode.trim()) {
      showToast({ type: 'error', message: '请输入股票代码' });
      return;
    }
    if (!Number.isFinite(sharesNum) || sharesNum <= 0) {
      showToast({ type: 'error', message: '请输入有效股数' });
      return;
    }
    if (!price || Number.isNaN(Number(price)) || Number(price) <= 0) {
      showToast({ type: 'error', message: '请输入有效每股成本价' });
      return;
    }
    setBusy(true);
    const ok = await onAdd({
      stockCode: stockCode.trim(),
      ...(stockName.trim() ? { stockName: stockName.trim() } : {}),
      shares: sharesNum,
      costPrice: price,
    });
    setBusy(false);
    if (ok) {
      setStockCode('');
      setStockName('');
      setShares('');
      setCostPrice('');
    }
  };

  return (
    <Card padding="md" className="mb-4">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
        <div>
          <label className="text-xs text-text-sec block mb-1">股票代码</label>
          <input
            value={stockCode}
            onChange={(e) => setStockCode(e.target.value)}
            placeholder="600519 或 600519.SH"
            className="w-full px-2 py-1.5 text-sm border border-border-def rounded-sm bg-bg-surface focus:border-accent"
          />
        </div>
        <div>
          <label className="text-xs text-text-sec block mb-1">名称(可选)</label>
          <input
            value={stockName}
            onChange={(e) => setStockName(e.target.value)}
            placeholder="贵州茅台"
            className="w-full px-2 py-1.5 text-sm border border-border-def rounded-sm bg-bg-surface focus:border-accent"
          />
        </div>
        <div>
          <label className="text-xs text-text-sec block mb-1">股数</label>
          <input
            value={shares}
            onChange={(e) => setShares(e.target.value)}
            inputMode="numeric"
            placeholder="100"
            className="w-full px-2 py-1.5 text-sm border border-border-def rounded-sm bg-bg-surface focus:border-accent"
          />
        </div>
        <div>
          <label className="text-xs text-text-sec block mb-1">每股成本价</label>
          <input
            value={costPrice}
            onChange={(e) => setCostPrice(e.target.value)}
            inputMode="decimal"
            placeholder="1450.000"
            className="w-full px-2 py-1.5 text-sm border border-border-def rounded-sm bg-bg-surface focus:border-accent"
          />
        </div>
        <div className="flex gap-2">
          <Button variant="primary" onClick={submit} loading={busy} size="sm">
            保存
          </Button>
          <Button variant="ghost" onClick={onCancel} size="sm">
            取消
          </Button>
        </div>
      </div>
    </Card>
  );
}
