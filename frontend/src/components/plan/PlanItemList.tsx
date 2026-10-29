'use client';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import type {
  BattlePlanItem,
  BattlePlanPoolMeta,
  BattlePlanScopeRow,
} from '@/lib/planTypes';
import {
  FULFILLMENT_BADGE,
  type StockFulfillment,
  requirementOf,
} from '@/lib/planDerive';

const KIND_LABEL: Record<string, string> = {
  entry: '建仓',
  add: '加仓',
  exit: '止盈',
  stop: '止损',
  t_sell: '做T减',
  t_buyback: '做T接',
  watch: '观察',
  unlock: '解锁后',
  do_not: '别动',
};

const FULFILL_LABEL: Record<string, string> = {
  pending: '待验证',
  touched: '已触及',
  executed: '已执行',
  missed: '未触发',
  n_a: '不适用',
  no_data: '数据不足',
};

function dirClass(direction: string): string {
  if (direction === 'buy') return 'text-up';
  if (direction === 'sell') return 'text-down';
  return 'text-text-sec';
}

export function PlanItemList({
  items,
  targetDate,
  scope,
  pool,
  fulfillment,
  activeCode,
}: {
  items: BattlePlanItem[];
  targetDate: string | null;
  /** 持仓 / ★关注 身份 —— 票头徽章用 */
  scope?: BattlePlanScopeRow[] | undefined;
  /** 全市场滚动池 —— 票头「池 · 保留 / 新补位」徽章用 */
  pool?: BattlePlanPoolMeta | null | undefined;
  /** 昨日股票级兑现状态(code → 状态) */
  fulfillment?: Map<string, StockFulfillment> | undefined;
  /** 当前聚焦的票(从左栏锚点点击而来) */
  activeCode?: string | null | undefined;
}) {
  const byStock = new Map<string, BattlePlanItem[]>();
  for (const it of items) {
    const arr = byStock.get(it.stockCode) ?? [];
    arr.push(it);
    byStock.set(it.stockCode, arr);
  }

  const scopeByCode = new Map((scope ?? []).map((s) => [s.stockCode, s]));
  const poolByCode = new Map((pool?.members ?? []).map((m) => [m.stockCode, m]));

  if (items.length === 0) {
    return (
      <Card>
        <h3 className="text-sm font-semibold">明日操作预案</h3>
        <p className="mt-2 text-xs text-text-sec">
          当前覆盖的股票暂无操作预案 —— 明日仅观察,不主动开仓。
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-2.5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">明日操作预案</h3>
        <span className="text-[11px] text-text-ter">
          目标日 {targetDate ?? '—'} · 共 {items.length} 条 / {byStock.size} 只
        </span>
      </div>

      {Array.from(byStock, ([code, list]) => {
        const sc = scopeByCode.get(code);
        const pm = poolByCode.get(code);
        const ff = fulfillment?.get(code) ?? null;
        const requirement = requirementOf(list);
        return (
          <Card
            key={code}
            id={`plan-stock-${code}`}
            padding="none"
            data-testid={`plan-stock-${code}`}
            className={clsx(
              'overflow-hidden scroll-mt-16 transition-shadow',
              activeCode === code && 'ring-1 ring-accent',
            )}
          >
            {/* 票头:名称 / 代码 / 身份徽章 */}
            <div className="flex items-baseline gap-2 px-2.5 py-1.5 bg-surface-3 border-b border-border-def">
              <span className="text-[13px] font-semibold text-text-pri">
                {/* ⚠️ tsconfig 开了 `noUncheckedIndexedAccess` → `list[0]` 类型是
                    `BattlePlanItem | undefined`,直接写 list[0].stockName 编译不过。
                    必须用可选链。 */}
                {list[0]?.stockName ?? code}
              </span>
              <span className="font-mono text-[10.5px] text-text-ter">{code}</span>
              <div className="ml-auto flex items-center gap-1">
                {sc?.inPosition && (
                  <Badge variant="negative" outline>
                    持仓
                  </Badge>
                )}
                {sc?.isFavorite && (
                  <Badge variant="info" outline>
                    ★
                  </Badge>
                )}
                {pm && (
                  <Badge variant="pool" outline>
                    {pm.state === 'added' ? '池 · 新补位' : '池 · 保留'}
                  </Badge>
                )}
                {pm?.score != null && (
                  <Badge variant="neutral" outline>
                    4 因子分 {pm.score.toFixed(1)}
                  </Badge>
                )}
                {ff && (
                  <Badge variant={FULFILLMENT_BADGE[ff].tone} outline>
                    {FULFILLMENT_BADGE[ff].label}
                  </Badge>
                )}
              </div>
            </div>

            {/* 最新操作要求 —— 与左栏锚点行同一份文案(同一套派生函数) */}
            <div
              data-testid="stock-req"
              className="px-2.5 py-1.5 text-[11px] text-text-sec bg-surface-2 border-b border-border-def"
            >
              <span className="text-text-ter">最新操作要求</span>{' '}
              <span className="font-semibold text-text-pri">{requirement}</span>
            </div>

            {/* 预案条目:虚线分隔,不再套一层带边框的方框(双层边框压死了信息密度) */}
            <div className="px-2.5 py-0.5">
              {list.map((it, idx) => (
                <div
                  key={`${code}-${idx}`}
                  className="py-1.5 border-b border-dashed border-border-def last:border-b-0"
                >
                  <div className="flex items-center gap-2 text-xs">
                    <span className="rounded bg-bg-subtle border border-border-str px-1.5 py-0.5 text-[10px] text-text-sec">
                      {KIND_LABEL[it.itemKind] ?? it.itemKind}
                    </span>
                    <span className={`font-semibold ${dirClass(it.direction)}`}>{it.label}</span>
                    {it.triggerPrice !== null && (
                      <span className={`font-mono tabular-nums ${dirClass(it.direction)}`}>
                        {it.triggerPrice.toFixed(2)}
                      </span>
                    )}
                    {it.fulfillment !== 'pending' && (
                      <span className="ml-auto text-[10px] text-text-ter">
                        {FULFILL_LABEL[it.fulfillment] ?? it.fulfillment}
                      </span>
                    )}
                  </div>

                  <p className="mt-1 text-xs leading-relaxed text-text-pri">
                    {it.triggerCondition}
                  </p>

                  {it.basis.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {it.basis.map((b, bi) => (
                        <li key={bi} className="text-[11px] text-text-sec">
                          依据：{b}
                        </li>
                      ))}
                    </ul>
                  )}

                  {it.invalidIf && (
                    <p className="mt-1 text-[11px] text-warn">失效：{it.invalidIf}</p>
                  )}

                  {it.fulfillmentNote && (
                    <p className="mt-1 text-[11px] text-text-ter">{it.fulfillmentNote}</p>
                  )}
                </div>
              ))}
            </div>
          </Card>
        );
      })}
    </div>
  );
}
