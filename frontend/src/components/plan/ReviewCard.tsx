'use client';

import { Card } from '@/components/ui/Card';
import type { BattlePlanReview } from '@/lib/planTypes';

const LEVEL_STYLE: Record<string, string> = {
  // 「按计划执行」不是行情方向 → 用中性正文色(红=买/涨、绿=卖/跌,都不能用来表示"做得好")
  ok: 'text-text-pri',
  warn: 'text-warn',      // 琥珀只给预警:执行缺口
  danger: 'text-danger',  // 语义错误色:纪律问题
  flat: 'text-text-sec',
};

export function ReviewCard({ review }: { review: BattlePlanReview | null }) {
  const todos = review?.pendingTodos ?? [];
  return (
    <Card>
      <h3 className="text-sm font-semibold">今日复盘</h3>

      {/* 今日大盘实况 —— 与兑现比对是两个独立来源:
          market 是「今天大盘怎么走」(事实),fulfillment 是「昨天预案兑现没」(判定)。
          两者可能一个有值另一个没有,所以 market 单独渲染,不受下面那个分支影响。 */}
      {review?.market && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
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

      {!review || !review.fulfillment ? (
        <p className="mt-2 text-xs text-text-sec">
          {review?.note ?? '还没有可比的昨日预案 —— 生成一次作战计划后,明天这里会显示兑现情况。'}
        </p>
      ) : (
        <>
          <div className="mt-2 text-xs text-text-sec">
            昨日预案 {review.fulfillment.total} 条
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
            <span className="text-text-pri">执行 {review.fulfillment.executed}</span>
            <span className="text-warn">触及未做 {review.fulfillment.touched}</span>
            <span className="text-text-sec">未触发 {review.fulfillment.missed}</span>
            {review.fulfillment.na > 0 && (
              <span className="text-text-ter">不适用 {review.fulfillment.na}</span>
            )}
            {review.fulfillment.noData > 0 && (
              <span className="text-warn">数据不足 {review.fulfillment.noData}</span>
            )}
          </div>
          {/* ⚠️ 「昨日预案 N 条」与下面四个计数可能对不上 ——
              n_a(别动/解锁类)与 no_data(无行情数据)都**不计入统计**,
              但它们确实是「定过的预案」→ 必须显式列出,否则用户以为漏了几条。 */}
          <div
            className={`mt-1.5 text-xs font-semibold ${LEVEL_STYLE[review.fulfillment.verdictLevel] ?? ''}`}
          >
            {review.fulfillment.verdictLabel}
          </div>

          {todos.length > 0 && (
            <div className="mt-3 border-t border-border-def pt-2">
              <div className="text-[11px] text-text-ter">今日待办（条件已满足但未处理）</div>
              <ul className="mt-1 space-y-1">
                {todos.map((t, i) => (
                  <li key={i} className="text-xs text-text-pri">
                    <span className="font-semibold">{t.stockName ?? t.stockCode}</span>
                    {' · '}
                    {t.label}
                    {t.price !== null && <span className="font-mono"> {t.price.toFixed(2)}</span>}
                    <span className="block text-[11px] text-text-sec">{t.condition}</span>
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
