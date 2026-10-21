'use client';

import { useEffect, useMemo, useState } from 'react';

import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import clsx from 'clsx';
import { ChevronDown, Edit, Star } from 'reicon-react';

import { apiDelete, apiPatch, apiPost } from '@/lib/api';
import { useUIStore } from '@/stores/useUIStore';
import type { Quote } from '@/lib/types';

import { GlassCard } from '@/components/ui/GlassCard';
import { LiquidModal } from '@/components/ui/LiquidModal';
import { Button } from '@/components/ui/Button';
import { TransactionForm } from '@/components/transaction/TransactionForm';
import { pctClass, chipColor } from '@/lib/format';

export interface WatchItem {
  code: string;
  name: string | null;
  inPosition: boolean;
  quote: Quote | null;
  isFavorite: boolean;  // v0.5 特别关注
  /** M3.2 持仓行轻提示:浮亏/高集中度等预警,来自 /holdings-health */
  healthFlag?: 'loss' | 'concentration' | 'profit' | null;
  /** 浮动盈亏比例(%)= floatingPnl / totalCost × 100;持仓视角下直接显示在行里 */
  positionPnlPct?: number | null;
}

/**
 * 列表视角
 * - `watch`:全部自选(自选 ∪ 持仓)
 * - `favorite`:只看特别关注
 * - `position`:只看持仓
 *
 * 取值与 DeskTopBar 的 DeskTab 一致,便于直接透传,不做二次映射。
 */
export type WatchListMode = 'watch' | 'favorite' | 'position';

/** 各视角的标题 / 空态文案(标题要反映当前筛选,否则「持仓(5)」会挂在「盯盘」下面) */
const MODE_META: Record<WatchListMode, { title: string; empty: string }> = {
  watch: { title: '盯盘', empty: '暂无自选股,点击右上角「添加自选」' },
  favorite: { title: '关注', empty: '暂无特别关注股票,点击自选股票旁的 ⭐ 加入' },
  position: { title: '持仓', empty: '当前没有持仓,可在「自选」里点行尾「⋯」设持仓' },
};

/**
 * 盯盘列表
 *
 * 两种形态(v0.8 交易台):
 * - `panel`(默认):卡片式大行,用于页面底部的独立列表区
 * - `rail`:紧凑行(两行文字 + 右对齐现价/涨跌幅),用于交易台左侧 258px 窄栏
 *
 * 两种形态共用同一份交互逻辑(增删 / 特别关注 / 持仓编辑 / 右键菜单),
 * 避免复制组件导致两边行为漂移。
 */
export function WatchList({
  items,
  activeCode,
  mode,
  onSelect,
  onChanged,
  variant = 'panel',
}: {
  items: WatchItem[];
  activeCode: string | null;
  mode: WatchListMode;
  onSelect: (code: string) => void;
  onChanged: () => void;
  /** rail = 窄栏紧凑行;panel = 卡片式大行 */
  variant?: 'panel' | 'rail';
}) {
  const showToast = useUIStore((s) => s.showToast);
  const [showAdd, setShowAdd] = useState(false);
  const [clearTarget, setClearTarget] = useState<WatchItem | null>(null);
  const [addForm, setAddForm] = useState({ stockCode: '', stockName: '' });
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; item: WatchItem } | null>(null);
  const [removeTarget, setRemoveTarget] = useState<WatchItem | null>(null);
  // 设置持仓弹窗(直设股数/成本 or 录入流水)
  const [setPosTarget, setSetPosTarget] = useState<WatchItem | null>(null);
  const [posForm, setPosForm] = useState({ shares: '', costPrice: '' });
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

  // 渲染弹窗到 body:绕开 GlassCard.backdrop-filter 创建的 containing block,
  // 否则 fixed 定位相对 aside 收缩,无法在全宽显示
  const renderModal = (modal: React.ReactNode) =>
    mounted ? createPortal(modal, document.body) : null;

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

  const submitSetPosition = async () => {
    if (!setPosTarget) return;
    const shares = Number(posForm.shares);
    const price = posForm.costPrice.trim();
    if (!Number.isFinite(shares) || shares <= 0) {
      showToast({ type: 'warning', message: '请输入有效股数' });
      return;
    }
    if (!price || Number.isNaN(Number(price)) || Number(price) <= 0) {
      showToast({ type: 'warning', message: '请输入有效每股成本价' });
      return;
    }
    try {
      await apiPost('/positions', {
        stockCode: setPosTarget.code,
        stockName: setPosTarget.name ?? undefined,
        shares,
        costPrice: price,
      });
      showToast({ type: 'success', message: `${setPosTarget.name ?? setPosTarget.code} 持仓已保存` });
      setSetPosTarget(null);
      setPosForm({ shares: '', costPrice: '' });
      onChanged();
    } catch {
      /* toast 已由拦截器处理 */
    }
  };

  const openSetPos = (item: WatchItem) => {
    setSetPosTarget(item);
    setPosForm({ shares: '', costPrice: '' });
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

  const content = (
    <>
      <div
        className={clsx(
          'flex items-center justify-between gap-2 shrink-0',
          variant === 'rail'
            ? 'h-8 px-2.5 border-b border-border-def'
            : 'px-1 flex-wrap',
        )}
      >
        <div className="flex items-baseline gap-1.5 min-w-0">
          <span
            className={clsx(
              'font-semibold text-text-pri whitespace-nowrap',
              variant === 'rail' ? 'text-[11.5px]' : 'text-base',
            )}
          >
            {mode === 'watch' ? (variant === 'rail' ? '盯盘' : '盯盘列表') : MODE_META[mode].title}
          </span>
          <span className="text-[10px] text-text-ter font-mono">({items.length})</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() =>
              setSortDir((d) =>
                d === 'default' ? 'desc' : d === 'desc' ? 'asc' : 'default',
              )
            }
            className="flex items-center gap-1 text-[10.5px] text-text-ter hover:text-text-pri transition-colors"
            title="按涨幅排序(默认 / 降序 / 升序)"
          >
            {/* 窄栏里只留箭头,否则表头会被挤成竖排 */}
            {variant !== 'rail' && <span>按涨幅</span>}
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
          {/* 持仓视角是筛选视角,「加自选」加进来的票不会出现在这里 —— 收起来 */}
          {mode !== 'position' && (
            <Button
              size="sm"
              onClick={() => setShowAdd(true)}
              title="添加自选"
              className={variant === 'rail' ? '!px-1.5 !py-0.5 !text-[11px]' : undefined}
            >
              {variant === 'rail' ? '＋' : '＋ 添加自选'}
            </Button>
          )}
        </div>
      </div>

      <ul
        className={clsx(
          'overflow-y-auto min-h-0',
          variant === 'rail' ? 'flex-1' : 'space-y-1 max-h-[460px] pr-1',
        )}
      >
        {items.length === 0 && (
          <li className="text-text-ter text-sm text-center py-10">{MODE_META[mode].empty}</li>
        )}
        {sortedItems.map((it) => {
          const isActive = it.code === activeCode;
          const halted = it.quote != null && Number(it.quote.currentPrice) === 0;
          return (
            <motion.li
              key={it.code}
              layout
              onContextMenu={(e) => onContextMenu(e, it)}
              className="relative"
            >
              {variant === 'rail' ? (
                /* rail 形态:两行文字(名称 / 代码)+ 右对齐现价与涨跌幅。
                   窄栏放不下大卡片,行高压到 ~34px,43 只自选也能一屏扫完。
                   交互入口(设持仓 / 特别关注 / 清仓)收进右侧「⋯」菜单。 */
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelect(it.code)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onSelect(it.code);
                    }
                  }}
                  className={clsx(
                    'w-full flex items-center gap-1.5 px-2 py-1 text-left transition-colors border-b border-border-def/40 relative cursor-pointer',
                    isActive ? 'bg-accent-subtle' : 'hover:bg-bg-elevated',
                  )}
                >
                  {isActive && (
                    <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-accent" aria-hidden />
                  )}
                  <span className="min-w-0 flex-1 flex flex-col min-w-0">
                    <span className="flex items-center gap-1 min-w-0">
                      <span className="text-[12.5px] text-text-pri truncate leading-tight">
                        {it.name ?? it.code}
                      </span>
                      {it.inPosition &&
                        (mode === 'position' ? (
                          /* 持仓视角:每一行都是持仓,「持」徽标没有信息量 —— 换成浮盈比例。
                             红涨绿跌(A股),与顶栏「浮盈」同色系(pctClass)。 */
                          <span
                            className={clsx(
                              'text-[9.5px] font-mono font-semibold tabular-nums shrink-0',
                              pctClass(it.positionPnlPct),
                            )}
                            title={
                              it.positionPnlPct == null
                                ? '浮动盈亏(行情未就绪)'
                                : `浮动盈亏 ${it.positionPnlPct > 0 ? '+' : ''}${it.positionPnlPct.toFixed(2)}%`
                            }
                          >
                            {it.positionPnlPct == null
                              ? '--'
                              : `${it.positionPnlPct > 0 ? '+' : ''}${it.positionPnlPct.toFixed(2)}%`}
                          </span>
                        ) : (
                          <span className="text-[9px] px-1 rounded-xs bg-accent-subtle text-accent font-semibold shrink-0">
                            持
                          </span>
                        ))}
                      {/* 浮亏红点:持仓视角里已由浮盈比例精确表达,不再重复 */}
                      {it.healthFlag === 'loss' && mode !== 'position' && (
                        <span
                          className="w-1.5 h-1.5 rounded-full bg-down shrink-0"
                          title="持仓浮亏"
                          aria-label="浮亏预警"
                        />
                      )}
                      {it.healthFlag === 'concentration' && (
                        <span
                          className="w-1.5 h-1.5 rounded-full bg-warn shrink-0"
                          title="持仓集中度过高"
                          aria-label="高集中度预警"
                        />
                      )}
                      {it.isFavorite && (
                        <Star size={11} weight="Filled" className="text-warn shrink-0" />
                      )}
                    </span>
                    <span className="text-[9.5px] font-mono text-text-ter leading-tight">
                      {it.code}
                    </span>
                  </span>
                  <span className="text-[12px] font-mono tabular-nums text-text-pri w-[44px] text-right shrink-0">
                    {!it.quote ? '--' : halted ? '停牌' : it.quote.currentPrice}
                  </span>
                  <span
                    className={clsx(
                      'text-[10.5px] font-mono tabular-nums w-[48px] text-right shrink-0',
                      !it.quote || halted
                        ? 'text-text-ter'
                        : it.quote.changePct > 0
                          ? 'text-up'
                          : it.quote.changePct < 0
                            ? 'text-down'
                            : 'text-text-ter',
                    )}
                  >
                    {!it.quote
                      ? '--'
                      : halted
                        ? '停牌'
                        : `${it.quote.changePct > 0 ? '+' : ''}${it.quote.changePct.toFixed(2)}%`}
                  </span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                      setContextMenu({ x: Math.max(r.left - 90, 8), y: r.bottom, item: it });
                    }}
                    className="w-4 h-5 shrink-0 text-text-ter hover:text-text-pri transition-colors text-[13px] leading-none flex items-center justify-center"
                    title="更多操作(设持仓 / 特别关注 / 删除)"
                    aria-label="更多操作"
                  >
                    ⋯
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => onSelect(it.code)}
                  className={clsx(
                    'w-full flex items-center gap-3 rounded-2xl px-3 py-2.5 text-left transition-colors border border-transparent',
                    isActive
                      ? 'bg-accent-subtle ring-1 ring-accent/25'
                      : 'hover:bg-bg-subtle',
                  )}
                >
                <span
                  className={clsx(
                    'w-9 h-9 rounded-xl bg-gradient-to-br text-white text-sm font-bold flex items-center justify-center shrink-0 shadow-sm',
                    chipColor(it.code),
                  )}
                >
                  {(it.name ?? it.code).slice(0, 1)}
                </span>
                <div className="min-w-0 flex-1 flex items-center gap-2">
                  <span className="text-sm font-medium text-text-pri truncate">
                    {it.name ?? it.code}
                  </span>
                  {it.inPosition && (
                    <>
                      <span className="text-[10px] px-1.5 py-px rounded-full bg-accent-subtle text-accent border border-accent/25 shrink-0">
                        持仓
                      </span>
                      {/* M3.2 持仓行轻提示红点:浮亏=down / 集中度=warn / 浮盈=up */}
                      {it.healthFlag === 'loss' && (
                        <span
                          className="w-2 h-2 rounded-full bg-down shrink-0 animate-pulse"
                          title="持仓浮亏:点击右侧编辑查看明细"
                          aria-label="浮亏预警"
                        />
                      )}
                      {it.healthFlag === 'concentration' && (
                        <span
                          className="w-2 h-2 rounded-full bg-warn shrink-0"
                          title="持仓集中度过高:点击右侧编辑查看明细"
                          aria-label="高集中度预警"
                        />
                      )}
                    </>
                  )}
                  {it.isFavorite && (
                    <Star size={12} weight="Filled" className="text-yellow-400 shrink-0" />
                  )}
                  <span className="text-xs text-text-ter font-mono hidden sm:inline">{it.code}</span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      openSetPos(it);
                    }}
                    className="inline-flex items-center shrink-0"
                    title={it.inPosition ? '调整持仓(股数/成本)' : '设为持仓(股数/成本)'}
                  >
                    <Edit
                      size={13}
                      className="text-text-ter/60 hover:text-accent"
                    />
                  </button>
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
                <div className="text-sm font-mono font-medium text-text-pri w-24 text-right shrink-0">
                  {!it.quote ? '--' : halted ? '停牌' : it.quote.currentPrice}
                </div>
                <div className="w-20 flex justify-end shrink-0">
                  <span
                    className={clsx(
                      'px-2 py-1 rounded-lg text-xs font-mono font-semibold',
                      !it.quote || halted
                        ? 'bg-bg-subtle text-text-ter'
                        : it.quote.changePct > 0
                          ? 'bg-up-bg text-up'
                          : it.quote.changePct < 0
                            ? 'bg-down-bg text-down'
                            : 'bg-bg-subtle text-text-ter',
                    )}
                  >
                    {!it.quote
                      ? '--'
                      : halted
                        ? '停牌'
                        : `${it.quote.changePct > 0 ? '+' : ''}${it.quote.changePct.toFixed(2)}%`}
                  </span>
                </div>
                {it.inPosition && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setClearTarget(it);
                    }}
                    className="shrink-0 text-xs leading-none hover:scale-110 transition-transform"
                    title="一键清仓"
                  >
                    🛑
                  </button>
                )}
              </button>
              )}
            </motion.li>
          );
        })}
      </ul>

      {renderModal(
        <LiquidModal
          open={showAdd}
          onClose={() => setShowAdd(false)}
          title="添加自选"
          footer={
            <>
              <Button variant="secondary" onClick={() => setShowAdd(false)} className=" rounded-xl">
                取消
              </Button>
              <Button onClick={submitAdd} className="panel">添加</Button>
            </>
          }
        >
          <div className="space-y-3">
            <input
              value={addForm.stockCode}
              onChange={(e) => setAddForm({ ...addForm, stockCode: e.target.value })}
              placeholder="股票代码,如 600519"
              className="w-full px-3 py-2 text-sm rounded-lg bg-bg-subtle border border-border-def focus:border-accent outline-none text-text-pri placeholder:text-text-ter"
            />
            <input
              value={addForm.stockName}
              onChange={(e) => setAddForm({ ...addForm, stockName: e.target.value })}
              placeholder="名称(可选)"
              className="w-full px-3 py-2 text-sm rounded-lg bg-bg-subtle border border-border-def focus:border-accent outline-none text-text-pri placeholder:text-text-ter"
            />
          </div>
        </LiquidModal>,
      )}

      {renderModal(
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
        </LiquidModal>,
      )}

      {/* 右键菜单:portal 到 body 避开 GlassCard.backdrop-filter 创建的 containing block,
          否则 fixed 定位会相对 GlassCard 偏移 */}
      {contextMenu && mounted && createPortal(
        <div
          data-watchlist-ctxmenu
          className="fixed z-50 min-w-[10rem] rounded-xl bg-bg-elevated border border-border-str shadow-lg p-1 backdrop-blur"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            type="button"
            onClick={() => {
              setRemoveTarget(contextMenu.item);
              setContextMenu(null);
            }}
            className="w-full text-left px-3 py-1.5 rounded-lg text-xs text-text-sec hover:bg-bg-subtle hover:text-text-pri transition-colors"
          >
            删除自选
          </button>
          <button
            type="button"
            onClick={() => {
              openSetPos(contextMenu.item);
              setContextMenu(null);
            }}
            className="w-full text-left px-3 py-1.5 rounded-lg text-xs text-text-sec hover:bg-bg-subtle hover:text-text-pri transition-colors"
          >
            {contextMenu.item.inPosition ? '调整持仓' : '设为持仓'}
          </button>
          {contextMenu.item.inPosition && (
            <button
              type="button"
              onClick={() => {
                setClearTarget(contextMenu.item);
                setContextMenu(null);
              }}
              className="w-full text-left px-3 py-1.5 rounded-lg text-xs text-text-sec hover:bg-bg-subtle hover:text-text-pri transition-colors"
            >
              一键清仓
            </button>
          )}
          {/* 特别关注开关也放进菜单 ——
              rail 形态(窄栏)没有空间常驻星标按钮,右键菜单是它的等价入口 */}
          <button
            type="button"
            onClick={() => {
              void toggleFavorite(contextMenu.item.code, !contextMenu.item.isFavorite);
              setContextMenu(null);
            }}
            className="w-full text-left px-3 py-1.5 rounded-lg text-xs text-text-sec hover:bg-bg-subtle hover:text-text-pri transition-colors"
          >
            {contextMenu.item.isFavorite ? '取消特别关注' : '加入特别关注'}
          </button>
        </div>,
        document.body,
      )}

      {/* 删除确认 */}
      {renderModal(
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
        </LiquidModal>,
      )}

      {/* 设置持仓:直设股数/成本 or 录入流水(流水自动同步持仓) */}
      {renderModal(
        <LiquidModal
          open={setPosTarget !== null}
          onClose={() => setSetPosTarget(null)}
          size="lg"
          title={`${setPosTarget?.inPosition ? '调整持仓' : '设为持仓'} ${setPosTarget?.name ?? setPosTarget?.code ?? ''}`}
        >
          <div className="space-y-5">
            {/* ① 直接设置股数 + 成本 */}
            <div>
              <div className="text-xs text-text-sec mb-2">直接设置</div>
              <div className="flex gap-2 items-end">
                <div className="flex-1">
                <label className="text-xs text-text-ter block mb-1">股数</label>
                <input
                  type="number"
                  min={1}
                  step={100}
                  value={posForm.shares}
                  onChange={(e) => setPosForm({ ...posForm, shares: e.target.value })}
                  placeholder="100"
                  className="w-full px-2 py-1.5 text-sm rounded-lg bg-bg-surface border border-border-str focus:border-accent outline-none text-text-pri placeholder:text-text-ter"
                />
                </div>
                <div className="flex-1">
                <label className="text-xs text-text-ter block mb-1">每股成本价</label>
                <input
                  type="number"
                  step="0.001"
                  value={posForm.costPrice}
                  onChange={(e) => setPosForm({ ...posForm, costPrice: e.target.value })}
                  placeholder="10.500"
                  className="w-full px-2 py-1.5 text-sm rounded-lg bg-bg-surface border border-border-str focus:border-accent outline-none text-text-pri placeholder:text-text-ter"
                />
                </div>
                <Button onClick={submitSetPosition} className="panel" size="sm">
                  保存
                </Button>
              </div>
              <p className="text-xs text-text-ter mt-1.5">
                直接设置会覆盖当前持仓；或改用下方流水录入（推荐，自动同步成本与股数）。
              </p>
            </div>

            {/* ② 录入流水(自动同步持仓) */}
            <div className="border-t border-border-def pt-4">
              <div className="text-xs text-text-sec mb-2">录入流水（自动同步持仓）</div>
              {setPosTarget && (
                <TransactionForm
                  initialStockCode={setPosTarget.code}
                  onCancel={() => setSetPosTarget(null)}
                  onSuccess={() => {
                    setSetPosTarget(null);
                    showToast({ type: 'success', message: '流水已录入，持仓已同步' });
                    onChanged();
                  }}
                />
              )}
            </div>
          </div>
        </LiquidModal>,
      )}
    </>
  );

  return variant === 'rail' ? (
    <div className="w-full h-full min-h-0 flex flex-col overflow-hidden bg-bg-surface border-r border-border-def">
      {content}
    </div>
  ) : (
    <GlassCard
      variant="default"
      padding="md"
      className="w-full flex flex-col overflow-hidden gap-2"
    >
      {content}
    </GlassCard>
  );
}
