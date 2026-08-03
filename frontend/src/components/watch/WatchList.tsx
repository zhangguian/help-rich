'use client';

import { useEffect, useMemo, useState } from 'react';

import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import clsx from 'clsx';
import { ChevronDown, Star } from 'reicon-react';

import { apiDelete, apiPatch, apiPost } from '@/lib/api';
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
  isFavorite: boolean;  // v0.5 特别关注
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
  favoriteOnly,
  onSelect,
  onChanged,
}: {
  items: WatchItem[];
  activeCode: string | null;
  favoriteOnly: boolean;
  onSelect: (code: string) => void;
  onChanged: () => void;
}) {
  const showToast = useUIStore((s) => s.showToast);
  const [showAdd, setShowAdd] = useState(false);
  const [clearTarget, setClearTarget] = useState<WatchItem | null>(null);
  const [addForm, setAddForm] = useState({ stockCode: '', stockName: '' });
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; item: WatchItem } | null>(null);
  const [removeTarget, setRemoveTarget] = useState<WatchItem | null>(null);
  // portal 挂载标记:只在客户端渲染 portal,避免 SSR/CSR hydration mismatch
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // 排序:3 状态循环 默认 → 降序 → 升序;持久化到 localStorage
  type SortDir = 'default' | 'desc' | 'asc';
  const [sortDir, setSortDir] = useState<SortDir>('default');
  useEffect(() => {
    const v = localStorage.getItem('watchlist-sort');
    if (v === 'desc' || v === 'asc' || v === 'default') setSortDir(v);
  }, []);
  useEffect(() => {
    if (sortDir === 'default') localStorage.removeItem('watchlist-sort');
    else localStorage.setItem('watchlist-sort', sortDir);
  }, [sortDir]);
  // 没 quote 的 items 排最后
  const sortedItems = useMemo(() => {
    if (sortDir === 'default') return items;
    const arr = [...items];
    arr.sort((a, b) => {
      const ac = a.quote?.changePct ?? null;
      const bc = b.quote?.changePct ?? null;
      if (ac == null && bc == null) return 0;
      if (ac == null) return 1;
      if (bc == null) return -1;
      return sortDir === 'desc' ? bc - ac : ac - bc;
    });
    return arr;
  }, [items, sortDir]);

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
    const price = clearTarget.quote?.currentPrice;
    if (!price || Number(price) <= 0) {
      showToast({
        type: 'warning',
        message: '未获取到当前行情，无法清仓，请稍后再试',
      });
      return;
    }
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

  const onContextMenu = (e: React.MouseEvent, item: WatchItem) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, item });
  };

  const toggleFavorite = async (code: string, next: boolean) => {
    try {
      await apiPatch(`/watchlist/${encodeURIComponent(code)}`, { isFavorite: next });
      onChanged();
    } catch {
      /* toast 已由拦截器处理 */
    }
  };

  const submitRemove = async () => {
    if (!removeTarget) return;
    const code = removeTarget.code;
    const inPosition = removeTarget.inPosition;
    try {
      if (inPosition) {
        await apiDelete(`/positions/${encodeURIComponent(code)}`);
      } else {
        await apiDelete(`/watchlist/${encodeURIComponent(code)}`);
      }
      showToast({
        type: 'success',
        message: inPosition ? `已删除 ${code} 持仓及流水` : `已从自选移除 ${code}`,
      });
      setRemoveTarget(null);
      onChanged();
    } catch {
      /* toast 已由拦截器处理 */
    }
  };

  // 菜单打开时:点击外部 / Esc / 滚动 关闭
  useEffect(() => {
    if (!contextMenu) return;
    const onDocDown = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest('[data-watchlist-ctxmenu]')) {
        setContextMenu(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setContextMenu(null);
    };
    const onScroll = () => setContextMenu(null);
    document.addEventListener('mousedown', onDocDown);
    document.addEventListener('contextmenu', onDocDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      document.removeEventListener('mousedown', onDocDown);
      document.removeEventListener('contextmenu', onDocDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [contextMenu]);

  return (
    <GlassCard
      variant="active"
      padding="sm"
      className="h-full flex flex-col overflow-hidden gap-2"
    >
      <div className="flex items-center justify-between px-2 pt-1">
        <span className="text-sm font-semibold text-text-pri">盯盘</span>
        <button
          type="button"
          onClick={() =>
            setSortDir((d) =>
              d === 'default' ? 'desc' : d === 'desc' ? 'asc' : 'default',
            )
          }
          className="flex items-center gap-1 text-xs text-text-ter hover:text-text-pri"
          title="按涨幅排序(默认 / 降序 / 升序)"
        >
          <span>{items.length} 只</span>
          <ChevronDown
            size={12}
            strokeWidth={1.5}
            className={clsx(
              'transition-transform',
              sortDir === 'asc' && 'rotate-180',
              sortDir === 'default' && 'opacity-40',
            )}
          />
        </button>
      </div>

      <ul className="flex-1 overflow-y-auto space-y-1 min-h-0 pr-1">
        {items.length === 0 && (
          <li className="text-text-ter text-sm text-center py-8">
            {favoriteOnly ? '暂无特别关注股票，点击自选股票旁的 ⭐ 加入' : '暂无自选股，点击下方添加'}
          </li>
        )}
        {sortedItems.map((it) => {
          const isActive = it.code === activeCode;
          return (
            <motion.li
              key={it.code}
              layout
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              onContextMenu={(e) => onContextMenu(e, it)}
              className="relative"
            >
              {/* {isActive && (
                <motion.span
                  layoutId="watch-active-bar"
                  className="absolute left-0 top-1 bottom-1 w-0.5 rounded bg-accent"
                  transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                />
              )} */}
              <button
                onClick={() => onSelect(it.code)}
                className={`w-full flex items-center justify-between gap-2 rounded-xl px-3 py-2 text-left transition-colors ${
                  isActive ? 'liquid-glass-active' : ''
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
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void toggleFavorite(it.code, !it.isFavorite);
                      }}
                      className="inline-flex items-center shrink-0"
                      title={it.isFavorite ? '取消特别关注' : '加入特别关注'}
                    >
                      <Star
                        size={13}
                        weight={it.isFavorite ? 'Filled' : 'Outline'}
                        className={clsx(
                          'transition-colors',
                          it.isFavorite
                            ? 'text-yellow-400'
                            : 'text-text-ter/40 hover:text-yellow-400',
                        )}
                      />
                    </button>
                  </div>
                  <div className="text-xs text-text-ter font-mono">{it.code}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-sm font-mono text-text-pri">
                    {!it.quote ? '--' : Number(it.quote.currentPrice) === 0 ? '停牌' : it.quote.currentPrice}
                  </div>
                  <div className={`text-xs font-mono ${pctClass(it.quote?.changePct)}`}>
                    {!it.quote
                      ? '--'
                      : Number(it.quote.currentPrice) === 0
                        ? '停牌'
                        : `${it.quote.changePct > 0 ? '+' : ''}${it.quote.changePct.toFixed(2)}%`}
                  </div>
                </div>
              </button>
              {it.inPosition && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setClearTarget(it);
                  }}
                  className="absolute left-0 top-0  text-down text-xs px-1"
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
        <Button variant="secondary" className="w-full liquid-glass rounded-xl" onClick={() => setShowAdd(true)}>
          添加自选
        </Button>
      </div>

      <LiquidModal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        title="添加自选"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowAdd(false)} className=" rounded-xl">
              取消
            </Button>
            <Button onClick={submitAdd} className="liquid-glass rounded-xl">添加</Button>
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

      {/* 右键菜单:portal 到 body 避开 GlassCard.backdrop-filter 创建的 containing block,
          否则 fixed 定位会相对 GlassCard 偏移 */}
      {contextMenu && mounted && createPortal(
        <div
          data-watchlist-ctxmenu
          className="fixed z-50 min-w-[10rem] rounded-xl bg-bg-base border border-white/15 shadow-lg p-1"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            type="button"
            onClick={() => {
              setRemoveTarget(contextMenu.item);
              setContextMenu(null);
            }}
            className="w-full text-left px-3 py-1.5 rounded-lg text-xs text-text-sec hover:bg-white/10 hover:text-text-pri transition-colors"
          >
            删除自选
          </button>
          {contextMenu.item.inPosition && (
            <button
              type="button"
              onClick={() => {
                setClearTarget(contextMenu.item);
                setContextMenu(null);
              }}
              className="w-full text-left px-3 py-1.5 rounded-lg text-xs text-text-sec hover:bg-white/10 hover:text-text-pri transition-colors"
            >
              一键清仓
            </button>
          )}
        </div>,
        document.body,
      )}

      {/* 删除确认 */}
      <LiquidModal
        open={removeTarget !== null}
        onClose={() => setRemoveTarget(null)}
        title={`删除 ${removeTarget?.name ?? removeTarget?.code ?? ''}`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRemoveTarget(null)}>
              取消
            </Button>
            <Button onClick={submitRemove}>确认删除</Button>
          </>
        }
      >
        <div className="text-sm text-text-sec space-y-2">
          <p>
            将删除「{removeTarget?.code}」
            {removeTarget?.inPosition ? '持仓及其关联流水' : '自选'}。
          </p>
          {removeTarget?.inPosition && (
            <p className="text-text-ter text-xs">此操作不可撤销，请确认。</p>
          )}
        </div>
      </LiquidModal>
    </GlassCard>
  );
}
