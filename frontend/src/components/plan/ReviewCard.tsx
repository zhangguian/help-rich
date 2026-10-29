'use client';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import type { BattlePlanReview } from '@/lib/planTypes';

const LEVEL_STYLE: Record<string, string> = {
  // 「按计划执行」不是行情方向 → 用中性正文色(红=买/涨、绿=卖/跌,都不能用来表示"做得好")
  ok: 'text-text-pri',
  warn: 'text-warn',      // 琥珀只给预警:执行缺口
  danger: 'text-danger',  // 语义错误色:纪律问题
  flat: 'text-text-sec',
};

/**
 * 今日复盘(作战计划 v2 · **左栏底部**)
 *
 * 为什么从右栏挪到左栏底部:
 * 旧版把复盘卡塞在右栏「明日市场预期」下面,和待办一起被挤到右栏底部,
 * 而右栏一滚动就被长列表顶走 —— 复盘是「昨天干得怎么样」,应该和
 * 「今天盯哪些票」在同一条视线上。挪到左栏底部后,锚点栏看完顺势往下就是复盘。
 */
export function ReviewCard({ review }: { review: BattlePlanReview | null }) {
  const todos = review?.pendingTodos ?? [];
  const f = review?.fulfillment;

  return (
    <Card padding="sm" data-testid="review-card">
      <div className="flex items-baseline gap-2">
        <h3 className="text-xs font-semibold text-text-pri">今日复盘</h3>
      </div>

      {/* 今日大盘实况 —— 与兑现比对是两个独立来源:
          market 是「今天大盘怎么走」(事实),fulfillment 是「昨天预案兑现没」(判定)。
          两者可能一个有值另一个没有,所以 market 单独渲染,不受下面那个分支影响。 */}
      {review?.market && (
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px]">
          <span className="text-text-sec">
            上证 {review.market.indexClose?.toFixed(2) ?? '—'}
          </span>
          {review.market.changePct !== null && (
            <span className={review.market.changePct >= 0 ? 'text-up' : 'text-down'}>
              {review.market.changePct >= 0 ? '+' : ''}
              {review.market.changePct.toFixed(2)}%
            </span>
          )}
          {review.market.volumeNote && (
            <span className="text-text-ter">{review.market.volumeNote}</span>
          )}
        </div>
      )}

      {!f ? (
        <p className="mt-1.5 text-[11px] leading-relaxed text-text-sec">
          {review?.note ?? '还没有可比的昨日预案 —— 生成一次作战计划后,明天这里会显示兑现情况。'}
        </p>
      ) : (
        <>
          {/* 结论条:结论前置,一眼看到「昨天干得怎么样」 */}
          <div className="mt-1.5 flex items-baseline gap-2 px-1.5 py-1 rounded bg-bg-subtle">
            <span
              className={clsx(
                'text-[12px] font-semibold',
                LEVEL_STYLE[f.verdictLevel] ?? '',
              )}
            >
              {f.verdictLabel}
            </span>
            <span className="ml-auto font-mono text-[10px] text-text-ter">
              {f.total} 条
            </span>
          </div>

          {/* 计数表:每种兑现状态各占一行,说清「这一行是什么意思」 */}
          <table className="mt-1.5 w-full border-collapse text-[11px]">
            <tbody>
              <Row label="已执行(按计划操作)" value={f.executed} />
              <Row label="已触及(价格到了,没操作)" value={f.touched} tone="warn" />
              <Row label="未触发(当日没碰到价位)" value={f.missed} />
              {f.na > 0 && <Row label="不适用(纪律类预案)" value={f.na} muted />}
              {f.noData > 0 && (
                <Row label="数据不足(当天没行情,未判定)" value={f.noData} tone="warn" />
              )}
            </tbody>
          </table>

          {/* ⚠️ 「昨日预案 N 条」与上面几行可能对不上 ——
              n_a(别动/解锁类)与 no_data(无行情数据)都**不计入统计**,
              但它们确实是「定过的预案」→ 必须显式列出,否则用户以为漏了几条。 */}

          {todos.length > 0 && (
            <div className="mt-2 pt-1.5 border-t border-border-def">
              <div className="text-[10px] text-text-ter">
                今日待办(条件已满足、还没做)
              </div>
              <ul className="mt-1 space-y-0.5">
                {todos.map((t, i) => (
                  <li key={i} className="text-[11px] leading-snug text-text-pri">
                    <span className="font-semibold">{t.stockName ?? t.stockCode}</span>
                    {' · '}
                    {t.label}
                    {t.price !== null && <span className="font-mono"> {t.price.toFixed(2)}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

/** 计数表的一行 */
function Row({
  label,
  value,
  tone,
  muted,
}: {
  label: string;
  value: number;
  tone?: 'warn';
  muted?: boolean;
}) {
  return (
    <tr>
      <td className={clsx('py-0.5 align-top', muted ? 'text-text-ter' : 'text-text-sec')}>
        {label}
      </td>
      <td
        className={clsx(
          'py-0.5 text-right align-top font-mono tabular-nums whitespace-nowrap',
          tone === 'warn' ? 'text-warn' : muted ? 'text-text-ter' : 'text-text-pri',
        )}
      >
        {value}
      </td>
    </tr>
  );
}
