'use client';

import { Card } from '@/components/ui/Card';
import type { BattlePlanItem } from '@/lib/planTypes';

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
}: {
  items: BattlePlanItem[];
  targetDate: string | null;
}) {
  const byStock = new Map<string, BattlePlanItem[]>();
  for (const it of items) {
    const arr = byStock.get(it.stockCode) ?? [];
    arr.push(it);
    byStock.set(it.stockCode, arr);
  }

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
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">明日操作预案</h3>
        <span className="text-[11px] text-text-ter">
          目标日 {targetDate ?? '—'} · 共 {items.length} 条
        </span>
      </div>

      {Array.from(byStock, ([code, list]) => (
        <Card key={code}>
          <div className="flex items-baseline justify-between">
            <div className="text-sm font-semibold">
              {/* ⚠️ tsconfig 开了 `noUncheckedIndexedAccess` → `list[0]` 类型是
                  `BattlePlanItem | undefined`,直接写 list[0].stockName 编译不过。
                  必须用可选链。 */}
              {list[0]?.stockName ?? code}{' '}
              <span className="ml-1 font-mono text-[11px] text-text-ter">{code}</span>
            </div>
          </div>

          <div className="mt-2 space-y-2">
            {list.map((it, idx) => (
              <div key={`${code}-${idx}`} className="rounded border border-border-def p-2.5">
                <div className="flex items-center gap-2 text-xs">
                  <span className="rounded bg-bg-subtle px-1.5 py-0.5 text-[10px] text-text-sec">
                    {KIND_LABEL[it.itemKind] ?? it.itemKind}
                  </span>
                  <span className={`font-semibold ${dirClass(it.direction)}`}>{it.label}</span>
                  {it.triggerPrice !== null && (
                    <span className={`font-mono ${dirClass(it.direction)}`}>
                      {it.triggerPrice.toFixed(2)}
                    </span>
                  )}
                  {it.fulfillment !== 'pending' && (
                    <span className="ml-auto text-[10px] text-text-ter">
                      {FULFILL_LABEL[it.fulfillment] ?? it.fulfillment}
                    </span>
                  )}
                </div>

                <p className="mt-1.5 text-xs leading-relaxed text-text-pri">
                  {it.triggerCondition}
                </p>

                {it.basis.length > 0 && (
                  <ul className="mt-1.5 space-y-0.5">
                    {it.basis.map((b, bi) => (
                      <li key={bi} className="text-[11px] text-text-sec">
                        依据：{b}
                      </li>
                    ))}
                  </ul>
                )}

                {it.invalidIf && (
                  <p className="mt-1.5 text-[11px] text-warn">失效：{it.invalidIf}</p>
                )}

                {it.fulfillmentNote && (
                  <p className="mt-1.5 text-[11px] text-text-ter">{it.fulfillmentNote}</p>
                )}
              </div>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}
