'use client';

import { useState } from 'react';

import { motion } from 'framer-motion';

import { apiPost } from '@/lib/api';
import { useUIStore } from '@/stores/useUIStore';
import type { Quote } from '@/lib/types';

import { GlassCard } from '@/components/ui/GlassCard';
import { LiquidModal } from '@/components/ui/LiquidModal';
import { Button } from '@/components/ui/Button';

export interface WatchItem {
  code: string;
  name: string | null;
  inPosition: boolean;
  quote: Quote | null;
}

/**
 * 左侧盯盘 aside(roadmap 功能1)
 *
 * 自选(含持仓)列表:现价/涨跌幅,选中 layoutId 滑块 + 左边条。
 * 持仓行尾 🛑 清仓(LiquidModal,默认实时价)。
 */
export function WatchList({
  items,
  activeCode,
  onSelect,
  onChanged,
}: {
  items: WatchItem[];
  activeCode: string | null;
  onSelect: (code: string) => void;
  onChanged: () => void;
}) {
  const showToast = useUIStore((s) => s.showToast);
  const [showAdd, setShowAdd] = useState(false);
  const [clearTarget, setClearTarget] = useState<WatchItem | null>(null);
  const [addForm, setAddForm] = useState({ stockCode: '', stockName: '' });

  const pctClass = (v: number | null | undefined) => {
    if (v == null) return 'text-text-ter';
    return v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-text-ter';
  };

  const submitAdd = async () => {
    const code = addForm.stockCode.trim();
    if (!code) {
      showToast({ type: 'warning', message: '请输入股票代码' });
      return;
    }
    try {
      await apiPost('/watchlist', {
        stockCode: code,
        stockName: addForm.stockName.trim() || undefined,
      });
      showToast({ type: 'success', message: '已加入自选' });
      setShowAdd(false);
      setAddForm({ stockCode: '', stockName: '' });
      onChanged();
    } catch {
      /* toast 已由拦截器处理 */
    }
  };

  const submitClear = async () => {
    if (!clearTarget) return;
    const price = clearTarget.quote?.currentPrice ?? undefined;
    try {
      const r = await apiPost<{ realizedPnl: string }>(`/positions/${clearTarget.code}/clear`, {
        price,
      });
      showToast({
        type: 'success',
        message: `已清仓,实现盈亏 ¥${r.realizedPnl}`,
      });
      setClearTarget(null);
      onChanged();
    } catch {
      /* toast 已由拦截器处理 */
    }
  };

  return (
    <GlassCard
      variant="active"
      padding="sm"
      className="h-full flex flex-col overflow-hidden gap-2"
    >
      <div className="flex items-center justify-between px-2 pt-1">
        <span className="text-sm font-semibold text-text-pri">盯盘</span>
        <span className="text-xs text-text-ter">{items.length} 只</span>
      </div>

      <ul className="flex-1 overflow-y-auto space-y-1 min-h-0 pr-1">
        {items.length === 0 && (
          <li className="text-text-ter text-sm text-center py-8">
            暂无自选股,点击下方添加
          </li>
        )}
        {items.map((it) => {
          const isActive = it.code === activeCode;
          return (
            <motion.li
              key={it.code}
              layout
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              className="relative"
            >
              {isActive && (
                <motion.span
                  layoutId="watch-active-bar"
                  className="absolute left-0 top-1 bottom-1 w-0.5 rounded bg-accent"
                  transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                />
              )}
              <button
                onClick={() => onSelect(it.code)}
                className={`w-full flex items-center justify-between gap-2 rounded-xl px-3 py-2 text-left transition-colors ${
                  isActive ? 'bg-accent-subtle' : 'hover:bg-white/5'
                }`}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm text-text-pri truncate">
                      {it.name ?? it.code}
                    </span>
                    {it.inPosition && (
                      <span className="text-[10px] px-1 py-px rounded bg-accent-subtle text-accent border border-accent/30">
                        持仓
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-text-ter font-mono">{it.code}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-sm font-mono text-text-pri">
                    {it.quote ? it.quote.currentPrice : '--'}
                  </div>
                  <div className={`text-xs font-mono ${pctClass(it.quote?.changePct)}`}>
                    {it.quote ? `${it.quote.changePct > 0 ? '+' : ''}${it.quote.changePct.toFixed(2)}%` : '--'}
                  </div>
                </div>
              </button>
              {it.inPosition && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setClearTarget(it);
                  }}
                  className="absolute left-0 top-0  text-text-ter hover:text-down text-xs px-1"
                  title="一键清仓"
                >
                  🛑
                </button>
              )}
            </motion.li>
          );
        })}
      </ul>

      <div className="pt-1 border-t border-white/5">
        <Button variant="secondary" className="w-full" onClick={() => setShowAdd(true)}>
          ➕ 添加自选
        </Button>
      </div>

      <LiquidModal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        title="添加自选"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowAdd(false)}>
              取消
            </Button>
            <Button onClick={submitAdd}>添加</Button>
          </>
        }
      >
        <div className="space-y-3">
          <input
            value={addForm.stockCode}
            onChange={(e) => setAddForm({ ...addForm, stockCode: e.target.value })}
            placeholder="股票代码,如 600519"
            className="w-full px-3 py-2 text-sm rounded-lg bg-white/5 border border-white/10 focus:border-accent outline-none text-text-pri placeholder:text-text-ter"
          />
          <input
            value={addForm.stockName}
            onChange={(e) => setAddForm({ ...addForm, stockName: e.target.value })}
            placeholder="名称(可选)"
            className="w-full px-3 py-2 text-sm rounded-lg bg-white/5 border border-white/10 focus:border-accent outline-none text-text-pri placeholder:text-text-ter"
          />
        </div>
      </LiquidModal>

      <LiquidModal
        open={clearTarget !== null}
        onClose={() => setClearTarget(null)}
        title={`一键清仓 ${clearTarget?.name ?? clearTarget?.code ?? ''}`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setClearTarget(null)}>
              取消
            </Button>
            <Button onClick={submitClear}>确认清仓</Button>
          </>
        }
      >
        <p className="text-sm text-text-sec">
          将以实时价
          <span className="font-mono text-text-pri">
            {' '}{clearTarget?.quote?.currentPrice ?? '--'}{' '}
          </span>
          生成卖出流水并结算实际盈亏。确认?
        </p>
      </LiquidModal>
    </GlassCard>
  );
}
