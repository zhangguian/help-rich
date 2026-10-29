'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

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

/**
 * 档位时间序。
 *
 * ⚠️ 不要靠数组下标判断「最新那档」—— `producedSlots` 的顺序是后端契约,
 * 但显式按时间排一次更稳(免得后端哪天改了排序,前端就静默指错档)。
 */
const SLOT_ORDER: Record<IntradaySlot, number> = { '11:30': 0, '14:00': 1 };

/** 面板轮询今日状态的间隔(ms)—— 调度器每 60s 醒一次,取一半保证不漏 */
const SCHEDULE_POLL_MS = 30000;

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
  const loadSchedule = useIntradayStore((s) => s.loadSchedule);
  const [slot, setSlot] = useState<IntradaySlot>('11:30');
  const [review, setReview] = useState<IntradayReview | null>(null);
  const [loading, setLoading] = useState(false);
  const [missing, setMissing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const produced = schedule?.producedSlots ?? [];
  const missingSlots = schedule?.missingSlots ?? [];

  /** 已产出里时间最晚的那档(按时间排,不靠数组下标) */
  const latestProduced = produced.length
    ? produced.reduce((a, b) => (SLOT_ORDER[b] > SLOT_ORDER[a] ? b : a))
    : null;

  /** 已产出档位的指纹 —— 变了就说明「有新的档产出了」,要重新取数据 */
  const producedKey = produced.join(',');

  // ⚠️ 2026-10-27 修复:新档产出 → **自动切过去**
  //
  // 事故:面板打开后**从不轮询**,所以 11:30 档在面板打开后才产出时,
  // 面板永远停在「下一次盘中复盘 11:30,还有 1 分钟」的空态;
  // 状态刷新后倒计时又直接跳到「下一次 14:00」——
  // 用户看到的就永远是倒计时,**复盘内容一次都没露出来**。
  //
  // 这里只在「最新档**变了**」时切(不是每次轮询都切),
  // 所以用户手动点档位标签切回旧档后,不会被下一次轮询拽走。
  const prevLatestRef = useRef<IntradaySlot | null>(null);
  useEffect(() => {
    if (!latestProduced) {
      prevLatestRef.current = null;
      return;
    }
    const prev = prevLatestRef.current;
    prevLatestRef.current = latestProduced;
    if (prev !== latestProduced) setSlot(latestProduced);
  }, [latestProduced]);

  // 打开时轮询今日状态(30s)—— 新档产出了才能自动切过去
  useEffect(() => {
    if (!open) return;
    void loadSchedule();
    const timer = setInterval(() => {
      void loadSchedule();
    }, SCHEDULE_POLL_MS);
    return () => clearInterval(timer);
  }, [open, loadSchedule]);

  // 按当前档位取数据
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
    // ⚠️ `producedKey` 必须在依赖里:「面板先开着、档位后产出」时 slot 没变,
    // 但 producedKey 变了 → 这里要重新取,否则面板停在空态。
  }, [open, slot, schedule?.date, producedKey]);

  // ESC 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // ⚠️ 陈旧内容守卫:切档后旧档的复盘还在 state 里,
  // 直接渲染会出现「标题写着 14:00、内容却是 11:30」—— 等于给了用户一份错的复盘。
  const shownReview = review && review.slot === slot ? review : null;

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const a of shownReview?.actions ?? []) c[a.actionState] = (c[a.actionState] ?? 0) + 1;
    return c;
  }, [shownReview]);

  const sortedActions = useMemo(() => {
    const list = [...(shownReview?.actions ?? [])];
    list.sort((a, b) => {
      const d = STATE_ORDER.indexOf(a.actionState) - STATE_ORDER.indexOf(b.actionState);
      return d !== 0 ? d : a.stockCode.localeCompare(b.stockCode);
    });
    return list;
  }, [shownReview]);

  if (!open) return null;

  const mo = shownReview?.marketOpinion;
  const kl = mo?.keyLevels ?? null;
  /** 当前看的这档是不是「已到点但还没产出」 */
  const slotMissing = missingSlots.includes(slot);

  /**
   * 顶部档位切换:已产出的 + 到点却没产出的**都列出来**。
   *
   * ⚠️ 为什么把「待补」那档也放进来:只列已产出的档位时,
   * 今天只产出了 14:00 的话标签行根本不渲染(只有 1 档)——
   * 用户点不到缺的那档,也就看不到「为什么这一档是空的」。
   * 列出来之后,点「11:30 待补」能直接看到「今天的 11:30 档还没产出」。
   */
  const tabSlots = [...produced, ...missingSlots]
    .filter((s, i, arr) => arr.indexOf(s) === i)
    .sort((a, b) => SLOT_ORDER[a] - SLOT_ORDER[b]);

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
                盘中复盘{shownReview ? ` · ${shownReview.slot}` : ''}
              </h2>
              {tabSlots.length > 1 && (
                <div className="flex gap-1">
                  {tabSlots.map((s) => {
                    const isMissing = missingSlots.includes(s);
                    return (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setSlot(s)}
                        className={`rounded px-1.5 py-0.5 text-[11px] ${
                          s === slot
                            ? isMissing
                              ? 'bg-warn-bg text-warn'
                              : 'bg-accent-subtle text-accent'
                            : isMissing
                              ? 'text-warn/70 hover:text-warn'
                              : 'text-text-ter hover:text-text-sec'
                        }`}
                      >
                        {s}
                        {isMissing ? ' 待补' : ''}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            <div className="mt-0.5 text-[11px] text-text-ter">
              {shownReview
                ? `${shownReview.tradeDate} · 共 ${shownReview.actions.length} 条预案 · 覆盖 ${shownReview.scopeCount ?? '—'} 只`
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

          {!loading && !shownReview && (
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
              ) : slotMissing ? (
                /* ⚠️ 这一档「**已经到点**但还没产出」——
                   绝不能再显示成「下一次盘中复盘 11:30,还有 1287 分钟」:
                   那会让用户以为 11:30 还没到点,于是永远等不到复盘,
                   而事实是那一档已经错过、只等补跑。 */
                <>
                  <div className="text-sm text-text-sec">今天的 {slot} 档还没产出</div>
                  <div className="mt-2 text-xs text-text-ter">
                    已到触发时刻但没产出
                    {missingSlots.length > 1 ? `(${missingSlots.join('、')})` : ''}。
                    系统会在补跑有效期内自动重试(11:30 档截止 14:29,14:00 档截止 15:59)。
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

          {shownReview && (
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
                      {/* ⚠️ key 必须带下标:`code-label-triggerPrice` 会撞 ——
                          同一只票可以有多条同 label、触发价同为 null 的动作
                          (如「明日别动」这类纪律类预案)。
                          key 撞了 React 会警告,并且**可能丢弃或重复渲染行** ——
                          表现就是「表格里的预案少了几条」,用户看到的是残缺的复盘。 */}
                      {sortedActions.map((a: IntradayAction, i: number) => (
                        <tr key={`${a.stockCode}-${a.label}-${a.triggerPrice}-${i}`} className="border-b border-border-def/40">
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
                  仅列前 12 条(共 {shownReview.actions.length} 条),完整清单见「作战计划」页
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
                {shownReview.extraLines.length > 0 ? (
                  <div className="space-y-1 text-[11.5px] leading-relaxed text-text-sec">
                    {shownReview.extraLines.map((line, i) => (
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
