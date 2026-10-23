'use client';

import { useEffect, useMemo, useState } from 'react';

import {
  fetchIntradayReview,
  type IntradayAction,
  type IntradayActionState,
  type IntradayReview,
  type IntradaySlot,
} from '@/lib/api/advanced';
import { useIntradayStore } from '@/stores/useIntradayStore';

/**
 * 盯盘页「盘中复盘」抽屉(阶段 10 · T3)
 *
 * **它是什么**:每个交易日 11:30 与 14:00 各做一次盘中复盘,给出
 * 「市场意见 + 逐票操作建议」。抽屉是它在盯盘页上的落点 ——
 * 之前调度只在 /brief 那个独立页挂着,盯盘页一个入口都没有。
 *
 * **市场意见的口径**:盘前四维度推断的结果,**不是盘中重算**。
 * 面板上标了「盘前四维度推断 · 非盘中重算」,免得把两套口径混着看。
 *
 * **逐票动作的口径**:拿「现价 vs 触发价」比出来的动作状态,
 * 与阶段9 的「兑现」(昨天说的今天做到了没)是两回事。
 */

const STATE_ORDER: IntradayActionState[] = ['已到价待执行', '未到价', '数据不足', '不适用'];

function stateClass(state: IntradayActionState): string {
  switch (state) {
    // 已到价待执行 = 要动手的信号 → 琥珀(预警语义)
    case '已到价待执行':
      return 'bg-warn-bg text-warn border-warn/40';
    // 未到价 = 中性
    case '未到价':
      return 'bg-bg-subtle text-text-sec border-border-str';
    // 数据不足 = 降级 → 虚线琥珀(与实心琥珀区分)
    case '数据不足':
      return 'bg-transparent text-warn border-warn/30 border-dashed';
    // 不适用 = 纪律类,不产生价格动作 → 最弱
    default:
      return 'bg-bg-subtle/60 text-text-ter border-border-str';
  }
}

function stanceClass(stance: string | null | undefined): string {
  if (stance === 'bullish') return 'text-up';
  if (stance === 'bearish') return 'text-down';
  return 'text-neutral';
}

function dimClass(score: number): string {
  if (score > 0) return 'text-up';
  if (score < 0) return 'text-down';
  return 'text-neutral';
}

function num(v: number | null | undefined): string {
  return v == null ? '—' : v.toFixed(2);
}

export default function IntradayReviewPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const schedule = useIntradayStore((s) => s.schedule);
  const [slot, setSlot] = useState<IntradaySlot>('11:30');
  const [review, setReview] = useState<IntradayReview | null>(null);
  const [loading, setLoading] = useState(false);
  const [missing, setMissing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 有两档就默认看最新那档
  useEffect(() => {
    const produced = schedule?.producedSlots ?? [];
    const latest = produced[produced.length - 1];
    if (latest) setSlot(latest);
  }, [schedule]);

  // 打开时按当前档位取数据
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    setMissing(false);
    setLoadError(null);
    void (async () => {
      try {
        const r = await fetchIntradayReview(slot, schedule?.date);
        if (!alive) return;
        setReview(r);
        setMissing(false);
      } catch (e) {
        if (!alive) return;
        // 404 = 这一档还没生成(正常业务语义)→ 空态
        // 其它错误(500 / 网络) → 单独提示,别谎报成「还没生成」
        const status = (e as { response?: { status?: number } })?.response?.status;
        setReview(null);
        setMissing(status === 404);
        if (status !== 404) {
          setLoadError(e instanceof Error ? e.message : '盘中复盘取数失败');
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [open, slot, schedule?.date]);

  // ESC 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const a of review?.actions ?? []) c[a.actionState] = (c[a.actionState] ?? 0) + 1;
    return c;
  }, [review]);

  const sortedActions = useMemo(() => {
    const list = [...(review?.actions ?? [])];
    list.sort((a, b) => {
      const d = STATE_ORDER.indexOf(a.actionState) - STATE_ORDER.indexOf(b.actionState);
      return d !== 0 ? d : a.stockCode.localeCompare(b.stockCode);
    });
    return list;
  }, [review]);

  if (!open) return null;

  const mo = review?.marketOpinion;
  const kl = mo?.keyLevels ?? null;
  const produced = schedule?.producedSlots ?? [];

  return (
    <>
      {/* 遮罩:点击关闭 */}
      <div
        className="fixed inset-0 z-40 bg-black/40"
        onClick={onClose}
        data-testid="intraday-review-mask"
      />
      <aside
        data-testid="intraday-review-panel"
        className="fixed right-0 top-0 z-50 flex h-full w-[560px] max-w-[92vw] flex-col
                   border-l border-border-str bg-bg-surface shadow-2xl"
      >
        {/* 头部 */}
        <header className="flex items-start gap-3 border-b border-border-def px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-text-pri">
                盘中复盘{review ? ` · ${review.slot}` : ''}
              </h2>
              {produced.length > 1 && (
                <div className="flex gap-1">
                  {produced.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setSlot(s)}
                      className={`rounded px-1.5 py-0.5 text-[11px] ${
                        s === slot
                          ? 'bg-accent-subtle text-accent'
                          : 'text-text-ter hover:text-text-sec'
                      }`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="mt-0.5 text-[11px] text-text-ter">
              {review
                ? `${review.tradeDate} · 共 ${review.actions.length} 条预案 · 覆盖 ${review.scopeCount ?? '—'} 只`
                : schedule?.date ?? ''}
            </div>
          </div>
          {mo?.stanceLabel && (
            <div className={`text-sm font-semibold ${stanceClass(mo.stance)}`}>
              倾向：{mo.stanceLabel}
            </div>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="text-lg leading-none text-text-ter hover:text-text-pri"
          >
            ×
          </button>
        </header>

        {/* 主体 */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {loading && <div className="py-8 text-center text-xs text-text-ter">加载中…</div>}

          {!loading && !review && (
            <div className="py-10 text-center">
              {loadError ? (
                <>
                  <div className="text-sm text-warn">盘中复盘取数失败</div>
                  <div className="mt-2 text-xs text-text-ter">{loadError}</div>
                </>
              ) : schedule && !schedule.isTradingDay ? (
                <>
                  <div className="text-sm text-text-sec">今天不是交易日</div>
                  <div className="mt-2 text-xs text-text-ter">
                    按上证指数真实交易日历判定,{schedule.date} 无盘中数据,盘中复盘不会跑
                    {schedule.tradingDayEstimated ? '(日历数据源不可用,当前为工作日推算)' : ''}
                  </div>
                </>
              ) : missing ? (
                <>
                  <div className="text-sm text-text-sec">
                    {schedule?.nextSlot
                      ? `下一次盘中复盘 ${schedule.nextSlot}${
                          schedule.nextSlotMinutesLeft != null
                            ? `,还有 ${schedule.nextSlotMinutesLeft} 分钟`
                            : ''
                        }`
                      : '这一档的盘中复盘还没生成'}
                  </div>
                  <div className="mt-2 text-xs text-text-ter">
                    每个交易日 11:30 与 14:00 各做一次,给出市场意见和逐票操作建议
                  </div>
                </>
              ) : (
                <div className="text-xs text-text-ter">盘中复盘状态取不到</div>
              )}
            </div>
          )}

          {review && (
            <>
              {/* 市场意见 */}
              <section className="mb-3 rounded-lg border border-border-def bg-bg-elevated p-3">
                <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold text-text-pri">
                  市场意见
                  <span className="rounded bg-bg-subtle px-1.5 py-0.5 text-[10px] font-normal text-text-ter">
                    盘前四维度推断 · 非盘中重算
                  </span>
                </div>
                {kl && (
                  <div className="mb-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[12px]">
                    <div>
                      <span className="text-text-ter">支撑 </span>
                      <span className="font-mono text-up">
                        {(kl.support ?? []).map((v) => v.toFixed(2)).join(' / ') || '—'}
                      </span>
                    </div>
                    <div>
                      <span className="text-text-ter">压力 </span>
                      <span className="font-mono text-down">
                        {(kl.resistance ?? []).map((v) => v.toFixed(2)).join(' / ') || '—'}
                      </span>
                    </div>
                    <div>
                      <span className="text-text-ter">收盘 </span>
                      <span className="font-mono text-text-sec">{num(kl.close)}</span>
                    </div>
                  </div>
                )}
                {mo?.summary && (
                  <p className="mb-2 text-[12px] leading-relaxed text-text-sec">{mo.summary}</p>
                )}
                <div className="grid gap-1">
                  {(mo?.dims ?? []).map((d) => (
                    <div key={d.key} className="flex items-baseline gap-2 text-[12px]">
                      <span className="w-16 shrink-0 text-text-ter">{d.label}</span>
                      <span className={`w-10 shrink-0 ${dimClass(d.score)}`}>
                        {d.score > 0 ? '偏多' : d.score < 0 ? '偏空' : '中性'}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-text-sec">{d.detail}</span>
                    </div>
                  ))}
                </div>
              </section>

              {/* 操作建议 */}
              <section className="mb-3 rounded-lg border border-border-def bg-bg-elevated p-3">
                <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold text-text-pri">
                  操作建议
                  <span className="rounded bg-bg-subtle px-1.5 py-0.5 text-[10px] font-normal text-text-ter">
                    按现价 vs 触发价
                  </span>
                </div>
                <div className="grid grid-cols-4 gap-2">
                  {STATE_ORDER.map((s) => {
                    const n = counts[s] ?? 0;
                    // 琥珀只给「有量」的预警/降级 —— 计数为 0 时不该用琥珀去点亮一个不存在的信号
                    const hot = s === '已到价待执行' ? 'text-warn' : s === '数据不足' && n > 0 ? 'text-warn' : 'text-text-sec';
                    return (
                      <div key={s} className="rounded-md border border-border-def bg-bg-surface px-2 py-1.5">
                        <div className={`text-base font-semibold ${hot}`}>{n}</div>
                        <div className="text-[10.5px] text-text-ter">{s}</div>
                      </div>
                    );
                  })}
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[520px] border-collapse text-[11.5px]">
                    <thead>
                      <tr className="border-b border-border-def text-text-ter">
                        <th className="py-1 pr-2 text-left font-normal">标的</th>
                        <th className="py-1 pr-2 text-left font-normal">动作</th>
                        <th className="py-1 pr-2 text-right font-normal">现价</th>
                        <th className="py-1 pr-2 text-right font-normal">触发价</th>
                        <th className="py-1 pr-2 text-right font-normal">差额</th>
                        <th className="py-1 pr-2 text-left font-normal">状态</th>
                        <th className="py-1 text-left font-normal">依据</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedActions.map((a: IntradayAction) => (
                        <tr key={`${a.stockCode}-${a.label}-${a.triggerPrice}`} className="border-b border-border-def/40">
                          <td className="py-1.5 pr-2">
                            <div className="text-text-pri">{a.stockName}</div>
                            <div className="font-mono text-[10px] text-text-ter">{a.stockCode}</div>
                          </td>
                          <td className="py-1.5 pr-2 text-text-sec" title={a.actionHint}>
                            {a.label || a.itemKind}
                          </td>
                          <td className="py-1.5 pr-2 text-right font-mono text-text-pri">{num(a.currentPrice)}</td>
                          <td className="py-1.5 pr-2 text-right font-mono text-text-sec">{num(a.triggerPrice)}</td>
                          <td
                            className={`py-1.5 pr-2 text-right font-mono ${
                              a.gapPct == null
                                ? 'text-text-ter'
                                : a.gapPct > 0
                                  ? 'text-up'
                                  : 'text-down'
                            }`}
                          >
                            {a.gapPct == null ? '—' : `${a.gapPct > 0 ? '+' : ''}${a.gapPct.toFixed(2)}%`}
                          </td>
                          <td className="py-1.5 pr-2">
                            <span
                              className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-[10.5px] ${stateClass(a.actionState)}`}
                            >
                              {a.actionState}
                            </span>
                          </td>
                          <td
                            className="max-w-[108px] truncate py-1.5 text-[10.5px] text-text-ter"
                            title={a.actionHint}
                          >
                            {Array.isArray(a.basis) ? a.basis.join(';') : (a.basis ?? '')}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-2 text-[10.5px] text-text-ter">
                  仅列前 12 条(共 {review.actions.length} 条),完整清单见「作战计划」页
                </div>
              </section>

              {/* 异动扫描补充段 */}
              <section className="rounded-lg border border-border-def bg-bg-elevated p-3">
                <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold text-text-pri">
                  异动扫描补充
                  <span className="rounded bg-bg-subtle px-1.5 py-0.5 text-[10px] font-normal text-text-ter">
                    与盘中复盘并入同一份产出
                  </span>
                </div>
                {review.extraLines.length > 0 ? (
                  <div className="space-y-1 text-[11.5px] leading-relaxed text-text-sec">
                    {review.extraLines.map((line, i) => (
                      <div key={i}>{line}</div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[11.5px] text-text-ter">本次没有额外异动扫描补充</div>
                )}
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
