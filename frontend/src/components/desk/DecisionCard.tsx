'use client';

import { useState } from 'react';

import clsx from 'clsx';

import type { DecisionAction, StockDecision } from '@/lib/types';

/**
 * 结论徽标配色 —— **不要**因为「红色看着像危险」就改回去。
 *
 * 本项目约定 **红=涨/买/看多,绿=跌/卖/看空**(A 股红涨绿跌):
 *   - components/desk/DecisionColumn.tsx:164(bullish→text-up / bearish→text-down)
 *   - components/paper/PaperTradingPanel.tsx:264(buy→text-danger / sell→text-success)
 *   - tailwind.config.ts:71-74(danger→up 色 / success→down 色,语义相同)
 * 所以 buy/add=红(看多)、sell=绿(看空)、reduce=琥珀(提示性动作)是对的。
 */
const VERDICT_META: Record<StockDecision['verdict'], { label: string; cls: string }> = {
  buy: { label: '可以建仓', cls: 'text-up border-up/40 bg-up-bg' },
  add: { label: '可以加仓', cls: 'text-up border-up/40 bg-up-bg' },
  hold: { label: '持股观察', cls: 'text-text-pri border-border-def bg-bg-subtle' },
  reduce: { label: '建议减仓', cls: 'text-warn border-warn/40 bg-warn-bg' },
  sell: { label: '建议止损', cls: 'text-down border-down/40 bg-down-bg' },
  wait: { label: '继续等待', cls: 'text-text-ter border-border-def bg-bg-subtle' },
};

/**
 * 状态徽标只表达**时态/强调程度**(现在/待触发/已否决),不承载方向色。
 *
 * 原因:`status` 是时态,`kind` 才是方向(买/卖)。
 * 若 `now` 固定用红色,一个 `kind:'stop'`(无条件止损)、`status:'now'` 的动作
 * 会显示成红色徽标「现在可做」——在红=涨=利好的语境下这是误导。
 * 「分批止盈」「破位减仓」同理。
 */
const STATUS_META: Record<DecisionAction['status'], { label: string; cls: string }> = {
  now: { label: '现在可做', cls: 'text-text-pri border-border-str bg-bg-elevated' },
  armed: { label: '待触发', cls: 'text-text-sec border-border-def bg-bg-subtle' },
  blocked: { label: '已否决', cls: 'text-text-ter border-border-def bg-bg-subtle' },
};

/**
 * 方向色跟**动作**走,跟状态无关。
 * 红=买/看多、绿=卖/看空 —— 与项目既有约定一致:
 *   - components/desk/DecisionColumn.tsx:164(bullish→text-up / bearish→text-down)
 *   - components/paper/PaperTradingPanel.tsx:264(buy→text-danger / sell→text-success)
 * 注意 danger/success 映射到的也是 up/down 两色(tailwind.config.ts:71-74),方向含义一致。
 */
const KIND_CLS: Record<DecisionAction['kind'], string> = {
  entry: 'text-up',
  add: 'text-up',
  t_buyback: 'text-up',
  exit: 'text-down',
  stop: 'text-down',
  t_sell: 'text-down',
  watch: 'text-text-pri',
};

function fmtNum(n: number | null | undefined, digits = 2): string {
  return n == null ? '--' : n.toFixed(digits);
}

/**
 * 操作决策卡(v0.9)
 *
 * **定位**:确定性引擎算出来的行动清单,**不是** LLM 解读。
 * 与 AI 解读冲突时以本卡为准(AI 只是一层白话解释)。
 *
 * 三态:loading(骨架)/ ready / error(显示降级原因,不空白)。
 *
 * **零编造**:所有数字都来自接口;缺数据显示「--」或降级文案,不拿 0 冒充。
 */
export function DecisionCard({
  decision,
  loading,
  error,
}: {
  decision: StockDecision | null;
  loading: boolean;
  error: string | null;
}) {
  const [showBlocked, setShowBlocked] = useState(false);

  if (loading) {
    return (
      <div className="rounded-md border border-border-def bg-bg-subtle p-3 space-y-2" aria-busy>
        <div className="h-4 w-1/2 rounded-sm bg-bg-elevated animate-pulse" />
        <div className="h-3 w-full rounded-sm bg-bg-elevated animate-pulse" />
        <div className="h-3 w-4/5 rounded-sm bg-bg-elevated animate-pulse" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md border border-border-def bg-bg-subtle p-3">
        <div className="text-[11px] font-semibold text-text-pri">操作决策</div>
        <div className="mt-1 text-[11px] text-text-ter">决策暂不可用:{error}</div>
      </div>
    );
  }

  if (!decision) {
    return (
      <div className="rounded-md border border-border-def bg-bg-subtle p-3">
        <div className="text-[11px] font-semibold text-text-pri">操作决策</div>
        <div className="mt-1 text-[11px] text-text-ter">选一只股票后给出买卖建议</div>
      </div>
    );
  }

  const vm = VERDICT_META[decision.verdict] ?? VERDICT_META.wait;
  const shown = decision.actions.filter((a) => a.status !== 'blocked');
  const blocked = decision.actions.filter((a) => a.status === 'blocked');
  const tp = decision.tPlan;
  const env = decision.marketEnv;

  return (
    <div className="rounded-md border border-border-def bg-bg-subtle p-3 space-y-2.5">
      {/* 头部:结论 */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[11px] font-semibold text-text-pri">操作决策</span>
        <span className={clsx('text-[10px] px-1.5 py-px rounded-sm border', vm.cls)}>{vm.label}</span>
        <span className="text-[10px] text-text-ter">{decision.role}</span>
        <span className="ml-auto text-[10px] text-text-ter">
          置信度{decision.confidence === 'high' ? '高' : decision.confidence === 'low' ? '低' : '中'}
        </span>
      </div>
      <div className="text-[11.5px] leading-[1.5] text-text-pri">{decision.headline}</div>

      {/* 行动清单 */}
      {shown.length > 0 ? (
        <ul className="space-y-1.5">
          {shown.map((a, i) => (
            <li key={`${a.kind}-${i}`} className="rounded-sm bg-bg-elevated px-2 py-1.5">
              <div className="flex items-center gap-1.5">
                <span className={clsx('text-[11px] font-medium', KIND_CLS[a.kind])}>{a.label}</span>
                <span className={clsx('text-[9px] px-1 py-px rounded-sm border', STATUS_META[a.status].cls)}>
                  {STATUS_META[a.status].label}
                </span>
                {a.price != null && (
                  <span className="ml-auto font-mono text-[11px] tabular-nums text-text-pri">
                    {fmtNum(a.price)} 元
                  </span>
                )}
              </div>
              <div className="mt-0.5 text-[10.5px] leading-[1.45] text-text-sec">{a.condition}</div>
              {a.basis.length > 0 && (
                <div className="mt-0.5 text-[9.5px] leading-[1.4] text-text-ter">{a.basis.join(' · ')}</div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <div className="text-[10.5px] text-text-ter">当前没有可执行动作,等条件触发。</div>
      )}

      {/* 仓位 / 止损 */}
      <div className="grid grid-cols-2 gap-1.5">
        <div className="rounded-sm bg-bg-elevated px-2 py-1.5">
          <div className="text-[9px] text-text-ter">仓位建议</div>
          <div className="mt-0.5 text-[10.5px] leading-[1.4] text-text-sec">
            {decision.positionPct || '暂无仓位建议'}
          </div>
        </div>
        <div className="rounded-sm bg-bg-elevated px-2 py-1.5">
          <div className="text-[9px] text-text-ter">止损</div>
          <div className="mt-0.5 text-[10.5px] leading-[1.4] text-text-sec">
            {decision.stopLoss
              ? `${fmtNum(decision.stopLoss.price)} 元(${decision.stopLoss.basis})`
              : '暂无止损位'}
          </div>
        </div>
      </div>

      {/* 做 T */}
      {tp && (
        <div className="rounded-sm bg-bg-elevated px-2 py-1.5">
          <div className="flex items-center gap-1.5">
            <span className="text-[9px] text-text-ter">做 T</span>
            {tp.suitable ? (
              <span className="text-[9.5px] text-up">可做</span>
            ) : (
              <span className="text-[9.5px] text-warn">不建议</span>
            )}
            {tp.suitable && (
              <span className="ml-auto font-mono text-[10px] tabular-nums text-text-pri">
                {fmtNum(tp.tLow)}~{fmtNum(tp.tHigh)} 元(振幅 {fmtNum(tp.amplitudePct, 1)}%)
              </span>
            )}
          </div>
          <div className="mt-0.5 text-[10px] leading-[1.4] text-text-sec">
            {tp.suitable ? (
              <>
                {tp.sellTrigger}
                <br />
                {tp.buybackTrigger}
                {tp.basePositionPct && <span> · 底仓留 {tp.basePositionPct}</span>}
                {tp.needsPosition && <span className="text-warn"> · 当前无底仓,做 T 前需先建仓</span>}
              </>
            ) : (
              (tp.unsuitableSignals || '当前条件不适合做 T')
            )}
          </div>
        </div>
      )}

      {/* 别动 */}
      {decision.doNot.length > 0 && (
        <div className="text-[10px] leading-[1.5] text-text-ter">
          <span className="text-warn">别动:</span> {decision.doNot.join(' · ')}
        </div>
      )}

      {/* 走势 / 市场环境 */}
      <div className="border-t border-border-def/60 pt-1.5 space-y-0.5">
        <div className="text-[10px] leading-[1.45] text-text-sec">
          <span className="text-text-ter">走势:</span> {decision.trendState.phase}
          <span className="text-text-ter"> · {decision.trendState.note}</span>
        </div>
        <div className="text-[10px] leading-[1.45] text-text-ter">
          {env.market.summary || '暂无数据'}
          {env.sector.summary && <span> · {env.sector.summary}</span>}
          {env.stockFlow.summary && <span> · {env.stockFlow.summary}</span>}
        </div>
        {env.relative.summary && (
          <div className="text-[10px] leading-[1.45] text-text-ter">{env.relative.summary}</div>
        )}
        {decision.dataQuality.degraded.length > 0 && (
          <div className="text-[9.5px] leading-[1.4] text-text-ter">
            降级:{decision.dataQuality.degraded.join(' · ')}
          </div>
        )}
      </div>

      {/* 已否决 */}
      {blocked.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setShowBlocked((v) => !v)}
            className="text-[10px] text-text-ter hover:text-text-sec"
          >
            {showBlocked ? '收起' : `为什么不做(${blocked.length})`}
          </button>
          {showBlocked && (
            <ul className="mt-1 space-y-1">
              {blocked.map((a, i) => (
                <li key={`b-${a.kind}-${i}`} className="rounded-sm bg-bg-subtle px-2 py-1">
                  <div className="text-[10.5px] text-text-sec">{a.label}</div>
                  {a.basis.length > 0 && (
                    <div className="text-[9.5px] text-text-ter">{a.basis.join(' · ')}</div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
