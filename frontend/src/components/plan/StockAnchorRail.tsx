'use client';

import { useState } from 'react';

import clsx from 'clsx';

import { Badge } from '@/components/ui/Badge';
import { pct, pctClass } from '@/lib/format';
import {
  FULFILLMENT_BADGE,
  type RailGroups,
  type RailStock,
} from '@/lib/planDerive';

/**
 * 股票锚点栏(作战计划 v2 · 左栏)
 *
 * **为什么要有这一栏**:旧版页面上,「今天要盯哪些票」和「每只票该做什么」
 * 分散在长列表里 —— 用户得先滚到中栏,再从 50 多条预案里反推自己盯的是哪几只。
 * 锚点栏把三件事压在同一列:
 *   1. 今天盯哪些票(持仓 / ★关注 / 全市场池,分组列清)
 *   2. 每只票**最新**的操作要求是什么(与中栏票头同一份文案)
 *   3. 昨天盯的结果(兑现徽章 + 连续未达天数)
 * 视线不用来回跳。
 *
 * 「最新操作要求」与「兑现徽章」都由 `@/lib/planDerive` 派生 ——
 * 中栏票头用的是同一套函数,两处不会漂移。
 */

/**
 * 分组默认**全部展开**
 *
 * ⚠️ 这里**不做自动折叠** —— 锚点栏的职责是「今天盯哪些票、每只票要做什么」,
 * 把票藏起来等于让用户点一下才知道自己的持仓要干什么(自动折叠过一次,
 * 22 只票只剩 9 只可见 —— 这是在替用户做决定)。
 * 想要更紧凑的用户可以**自己点组头折叠**。
 */

export function StockAnchorRail({
  groups,
  onSelect,
  activeCode,
}: {
  groups: RailGroups;
  /** 点击锚点 → 中栏滚到对应那只票 */
  onSelect?: ((code: string) => void) | undefined;
  /** 当前高亮的票(跟随中栏滚动或上次点击) */
  activeCode?: string | null | undefined;
}) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const toggle = (key: string) =>
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));

  const posCount = groups.positions.length;
  const favCount = groups.favorites.length;
  const poolCount = groups.pool.length + groups.dropped.length;

  return (
    <section
      data-testid="stock-anchor-rail"
      className="bg-surface-2 border border-border-def rounded-lg overflow-hidden"
    >
      {/* 栏头:今天盯盘清单 + 三类来源的只数
          ⚠️ 标题加 shrink-0 + whitespace-nowrap —— 236px 窄栏里
          「今日盯盘清单」会被 flex 挤断成「今日盯盘清 / 单」两行 */}
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-2.5 py-2 bg-surface-3 border-b border-border-def">
        <span className="text-xs font-semibold text-text-pri shrink-0 whitespace-nowrap">
          今日盯盘清单
        </span>
        <span className="ml-auto font-mono text-[10px] text-text-ter whitespace-nowrap">
          持仓 {posCount} · ★关注 {favCount} · 池 {poolCount}
        </span>
      </div>

      <Group
        title="持仓"
        count={posCount}
        stocks={groups.positions}
        groupKey="pos"
        collapsed={collapsed}
        onToggle={toggle}
        onSelect={onSelect}
        activeCode={activeCode}
      />
      <Group
        title="★关注"
        count={favCount}
        stocks={groups.favorites}
        groupKey="fav"
        collapsed={collapsed}
        onToggle={toggle}
        onSelect={onSelect}
        activeCode={activeCode}
      />
      <Group
        title="全市场滚动池"
        count={poolCount}
        stocks={[...groups.pool, ...groups.dropped]}
        groupKey="pool"
        collapsed={collapsed}
        onToggle={toggle}
        onSelect={onSelect}
        activeCode={activeCode}
      />
    </section>
  );
}

/** 一个分组(持仓 / ★关注 / 池)—— 组头可点,点一下折叠/展开该组 */
function Group({
  title,
  count,
  stocks,
  groupKey,
  collapsed,
  onToggle,
  onSelect,
  activeCode,
}: {
  title: string;
  count: number;
  stocks: RailStock[];
  groupKey: string;
  collapsed: Record<string, boolean>;
  onToggle: (key: string) => void;
  onSelect?: ((code: string) => void) | undefined;
  activeCode?: string | null | undefined;
}) {
  if (count === 0) return null;
  const isCollapsed = collapsed[groupKey] ?? false;

  return (
    <>
      <button
        type="button"
        onClick={() => onToggle(groupKey)}
        aria-expanded={!isCollapsed}
        className="flex w-full items-baseline gap-1.5 px-2.5 py-1 bg-surface-2 border-b border-border-def text-[10px] text-text-ter hover:text-text-sec"
      >
        <span className="text-[9px]">{isCollapsed ? '▸' : '▾'}</span>
        <span>
          {title}({count})
        </span>
        {isCollapsed && <span className="ml-auto">已折叠 · 点开</span>}
      </button>
      {!isCollapsed &&
        stocks.map((s) => (
          <AnchorRow
            key={`${groupKey}-${s.code}`}
            stock={s}
            onSelect={onSelect}
            active={activeCode === s.code}
          />
        ))}
    </>
  );
}

/** 一只票的锚点行 */
function AnchorRow({
  stock,
  onSelect,
  active,
}: {
  stock: RailStock;
  onSelect?: ((code: string) => void) | undefined;
  active: boolean;
}) {
  return (
    <button
      type="button"
      data-testid={`anchor-${stock.code}`}
      onClick={() => onSelect?.(stock.code)}
      className={clsx(
        'block w-full text-left px-2.5 py-1.5 border-b border-border-def last:border-b-0',
        'hover:bg-bg-elevated transition-colors',
        // 选中态:左侧一道强调色边 —— 有些票没有预案条目,点下去中栏没有对应卡片,
        // 没有这个反馈就等于「点了没反应」。
        active && 'bg-bg-elevated border-l-2 border-l-accent pl-2',
        stock.dropped && 'opacity-55',
      )}
    >
      {/* 第 1 行:名称 + 代码 + 涨跌幅 */}
      <div className="flex items-baseline gap-1.5">
        <span className="text-xs font-semibold text-text-pri truncate">{stock.name}</span>
        <span className="font-mono text-[10px] text-text-ter shrink-0">{stock.code}</span>
        <span
          className={clsx(
            'ml-auto font-mono text-[11px] shrink-0 tabular-nums',
            pctClass(stock.changePct),
          )}
        >
          {stock.changePct != null ? pct(stock.changePct) : '—'}
        </span>
      </div>

      {/* 第 2 行:身份徽章 + 昨日兑现 + 连续天数 */}
      <div className="mt-1 flex items-center gap-1 flex-wrap">
        {stock.inPosition && (
          <Badge variant="negative" outline>
            持仓
          </Badge>
        )}
        {stock.isFavorite && (
          <Badge variant="info" outline>
            ★
          </Badge>
        )}
        {stock.isPool && !stock.dropped && (
          <Badge variant="pool" outline>
            {stock.poolState === 'added' ? '池 · 新补位' : '池 · 保留'}
          </Badge>
        )}
        {stock.isPool && !stock.dropped && stock.poolScore != null && (
          <Badge variant="neutral" outline>
            4 因子分 {stock.poolScore.toFixed(1)}
          </Badge>
        )}
        {stock.dropped && (
          <Badge variant="negative" outline>
            已剔除出池
          </Badge>
        )}
        {stock.fulfillment && (
          <Badge variant={FULFILLMENT_BADGE[stock.fulfillment].tone} outline>
            {FULFILLMENT_BADGE[stock.fulfillment].label}
          </Badge>
        )}
        {stock.missStreak >= 1 && !stock.dropped && (
          <Badge variant="caution" outline>
            连续 {stock.missStreak} 天
          </Badge>
        )}
        {stock.dropped && (
          <Badge variant="caution" outline>
            连续 {stock.missStreak} 天未达预期
          </Badge>
        )}
      </div>

      {/* 第 3 行:最新操作要求 —— 与中栏票头同一份文案 */}
      <div
        data-testid="req-line"
        className={clsx(
          'mt-1 pl-1.5 border-l-2 text-[11px] leading-[1.45] text-text-sec break-words',
          stock.dropped
            ? 'border-border-str text-text-ter'
            : stock.missStreak >= 2
              ? 'border-warn'
              : 'border-accent',
        )}
      >
        <span className="text-text-ter">最新操作要求</span>{' '}
        <span className="font-semibold text-text-pri">{stock.requirement}</span>
      </div>

      {/* 被剔除的票:写清为什么被换掉 */}
      {stock.dropped && stock.dropReason && (
        <div className="mt-1 text-[10.5px] text-text-ter break-words">{stock.dropReason}</div>
      )}
    </button>
  );
}
