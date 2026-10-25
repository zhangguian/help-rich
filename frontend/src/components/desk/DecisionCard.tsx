'use client';

import { useState } from 'react';

import clsx from 'clsx';

import type {
  AnalysisResult,
  DecisionAction,
  DecisionAdviceText,
  DecisionGridPlan,
  DecisionSuggestions,
  StockDecision,
} from '@/lib/types';

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

/** 操作建议区 · 角色徽章配色(视觉稿 §az-head):
 *  止盈参考=红(浮盈)· 解套参考=琥珀(浮亏警示)· 建仓参考=中性强调色 */
const ADVICE_ROLE_CLS: Record<StockDecision['positionStatus'], string> = {
  profit: 'text-up border-up/40 bg-up-bg',
  loss: 'text-warn border-warn/40 bg-warn-bg',
  empty: 'text-accent border-accent/40 bg-accent-subtle/60',
};

/** 六格固定顺序(设计文档 §6.10)——顺序是阅读顺序,不要随手改 */
const ADVICE_CELLS: Array<{ key: keyof DecisionSuggestions; label: string }> = [
  { key: 'price', label: '价位' },
  { key: 'stopLoss', label: '止损' },
  { key: 'position', label: '仓位' },
  { key: 'trigger', label: '触发' },
  { key: 'timing', label: '时间' },
  { key: 'avoid', label: '不动' },
];

function fmtNum(n: number | null | undefined, digits = 2): string {
  return n == null ? '--' : n.toFixed(digits);
}

/** 金额:整数不带小数,避免「2500.00 元」这种噪音 */
function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '--';
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

/**
 * 六格缺值时的占位文案。
 *
 * ⚠️ 缺值**置灰占位、不隐藏整格**:数据缺失是常态(如未持仓就没有持有天数),
 * 藏掉整格会让用户以为「这条建议不存在」,而它其实只是「暂时算不出来」。
 * 但占位**不能编数字** —— 只说缺什么,不给猜测值。
 */
function advicePlaceholder(key: keyof DecisionSuggestions, d: StockDecision): string {
  switch (key) {
    case 'price':
      return '暂无价位信号';
    case 'stopLoss':
      return '暂无止损位';
    case 'position':
      return '暂无仓位建议';
    case 'trigger':
      return '暂无触发条件';
    case 'timing':
      return d.positionStatus === 'empty' ? '未持仓,无持有天数' : '持有天数不可用';
    case 'avoid':
      return '暂无别动信号';
  }
}

/** 折叠区「更多维度」的每一行(成本锚点 / 时间窗口 / 费用影响 / 品种规则 / 集中度) */
function adviceDims(d: StockDecision): Array<{ key: string; label: string; value: string }> {
  const out: Array<{ key: string; label: string; value: string }> = [];

  const ca = d.costAnchor;
  if (ca) {
    const bits: string[] = [];
    if (ca.pnlPct != null) {
      bits.push(`${ca.pnlPct >= 0 ? '浮盈' : '浮亏'} ${Math.abs(ca.pnlPct).toFixed(1)}%`);
    }
    // 浮盈看上行空间(到 P80 / 风险收益比),浮亏看下行风险(回本幅度 / 距止损)
    if (ca.pnlPct != null && ca.pnlPct >= 0) {
      if (ca.distanceToTargetPct != null) {
        bits.push(`到 P80 还有 +${ca.distanceToTargetPct.toFixed(1)}%`);
      }
      if (ca.riskReward != null) bits.push(`风险收益比 ${ca.riskReward.toFixed(2)}`);
    } else {
      if (ca.breakEvenGapPct != null) bits.push(`回本还需 +${ca.breakEvenGapPct.toFixed(1)}%`);
      if (ca.distanceToStopPct != null) bits.push(`距止损 ${ca.distanceToStopPct.toFixed(1)}%`);
    }
    if (bits.length > 0) out.push({ key: 'cost', label: '成本锚点', value: bits.join(' · ') });
  }

  const tw = d.timeWindow;
  if (tw) {
    const bits = [tw.note];
    if (tw.overdueText) bits.push(tw.overdueText);
    out.push({ key: 'time', label: '时间窗口', value: bits.join(' · ') });
  }

  const ce = d.costEffect;
  if (ce) {
    const bits: string[] = [];
    if (ce.roundtripFeePct != null) bits.push(`往返费率 ${ce.roundtripFeePct.toFixed(3)}%`);
    if (ce.spreadPct != null) bits.push(`做 T 差价 ${ce.spreadPct.toFixed(1)}%`);
    if (ce.worthIt != null) bits.push(ce.worthIt ? '划算' : '不划算');
    if (ce.note) bits.push(ce.note.replace(/[;；]\s*$/, ''));
    if (bits.length > 0) out.push({ key: 'fee', label: '费用影响', value: bits.join(' · ') });
  }

  const ir = d.instrumentRule;
  if (ir && ir.notes.length > 0) {
    out.push({ key: 'inst', label: '品种规则', value: ir.notes.join(' · ') });
  }

  const co = d.concentration;
  if (co?.note) out.push({ key: 'conc', label: '集中度', value: co.note });

  return out;
}

/** 白话来源:现场生成 > AI 解读 > 规则文案(永远有一句,不空白) */
function buildVoice(
  d: StockDecision,
  analysis: AnalysisResult | null,
  advice: DecisionAdviceText | null,
): { source: string; time: string | null; text: string; bullets: string[] } | null {
  if (advice?.headline) {
    return {
      source: advice.source === 'llm' ? 'AI 白话' : '规则文案',
      time: analysis?.latestKlineDate ?? null,
      text: advice.headline,
      bullets: advice.bullets ?? [],
    };
  }
  const rationale = analysis?.ai?.advice?.rationale;
  if (rationale) {
    return {
      source: 'AI 解读',
      time: analysis?.latestKlineDate ?? null,
      text: rationale,
      bullets: [],
    };
  }
  if (d.advice?.headline) {
    return {
      source: '规则文案',
      time: null,
      text: d.advice.headline,
      bullets: d.advice.bullets ?? [],
    };
  }
  return null;
}

/**
 * 操作决策卡(v0.10)
 *
 * **定位**:确定性引擎算出来的行动清单,**不是** LLM 解读。
 * 与 AI 解读冲突时以本卡为准(AI 只是一层白话解释)。
 *
 * v0.10 卡片结构(自上而下,按读卡顺序):
 *   1. 结论头 + headline
 *   2. **「操作建议」区** —— 六格要素 + 网格交易配置建议 + 白话 + 折叠维度
 *   3. 行动清单
 *   4. 做 T 块
 *   5. 别动 / 走势 / 市场环境 / 已否决
 *
 * **为什么操作建议区放在结论头之下、行动清单之上**:先给"照着做的建议"(六格),
 * 再给"为什么"(行动清单与依据)。六格与行动清单同源(同一份事实包),
 * 数字必须一致,不许两套说法。
 *
 * 三态:loading(骨架)/ ready / error(显示降级原因,不空白)。
 *
 * **零编造**:所有数字都来自接口;缺数据 → 置灰占位文案,不拿 0 冒充。
 */
export function DecisionCard({
  decision,
  loading,
  error,
  analysis,
  advice,
  adviceNote,
  adviceLoading,
  onWriteAdvice,
}: {
  decision: StockDecision | null;
  loading: boolean;
  error: string | null;
  /** AI 解读结果 —— 白话来源之一(analysis.ai.advice.rationale) */
  analysis: AnalysisResult | null;
  /** 「AI 写白话」现场生成的白话(优先于 analysis 里的白话) */
  advice: DecisionAdviceText | null;
  /** 现场生成时的降级说明(如「AI 白话不可用,已退回规则文案」) */
  adviceNote: string | null;
  adviceLoading: boolean;
  /** 触发「AI 写白话」(按钮显式烧 token) */
  onWriteAdvice: () => void;
}) {
  const [showBlocked, setShowBlocked] = useState(false);
  const [showDims, setShowDims] = useState(false);

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
  const grid = decision.gridPlan;
  const dims = adviceDims(decision);
  const voice = buildVoice(decision, analysis, advice);

  return (
    <div
      className="rounded-md border border-border-def bg-bg-subtle p-3 space-y-2.5"
      data-testid="decision-card"
    >
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

      {/* ============ 操作建议区(v0.10) ============ */}
      {decision.suggestions && (
        <div
          className="rounded-md border border-border-def bg-bg-subtle p-2.5 space-y-2"
          data-testid="advice-zone"
        >
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] font-semibold text-text-pri">操作建议</span>
            <span
              className={clsx(
                'text-[9.5px] px-1.5 py-px rounded-sm border',
                ADVICE_ROLE_CLS[decision.positionStatus],
              )}
            >
              {decision.role}
            </span>
            <span className="ml-auto text-[9.5px] text-text-ter">确定性引擎 · 实时</span>
          </div>

          {/* 六格:值为 null → 置灰占位,不编数字 */}
          <div className="grid grid-cols-2 gap-1.5" data-testid="advice-cells">
            {ADVICE_CELLS.map(({ key, label }) => {
              const cell = decision.suggestions?.[key] ?? null;
              const value = cell?.value ?? '';
              const missing = !value;
              return (
                <div
                  key={key}
                  data-testid={`advice-cell-${key}`}
                  data-missing={missing ? '1' : '0'}
                  className={clsx(
                    'rounded-sm px-2 py-1.5',
                    missing
                      ? 'border border-dashed border-border-def'
                      : 'bg-bg-elevated',
                  )}
                >
                  <div className={clsx('text-[9px]', missing ? 'text-text-ter/60' : 'text-text-ter')}>
                    {label}
                  </div>
                  <div
                    className={clsx(
                      'mt-0.5 leading-[1.4]',
                      missing
                        ? 'text-[9.5px] text-text-ter/60'
                        : 'text-[10.5px] text-text-sec',
                    )}
                  >
                    {missing ? advicePlaceholder(key, decision) : value}
                  </div>
                </div>
              );
            })}
          </div>

          {/* 网格交易配置建议(独立子块,与做 T 互斥) */}
          {grid && (
            <div
              data-testid="advice-grid"
              data-suitable={grid.suitable ? '1' : '0'}
              className={clsx(
                'rounded-sm border-l-2 px-2 py-1.5',
                grid.suitable
                  ? 'border-l-accent bg-bg-elevated'
                  : 'border-l-warn bg-bg-elevated',
              )}
            >
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[9px] text-text-ter">网格</span>
                <span
                  className={clsx(
                    'text-[9.5px] font-semibold px-1.5 py-px rounded-sm border',
                    grid.suitable
                      ? 'text-accent border-accent/40 bg-accent-subtle/60'
                      : 'text-warn border-warn/40 bg-warn-bg',
                  )}
                >
                  {grid.suitable ? '可配置' : '不建议'}
                </span>
                {grid.suitable && grid.mode && (
                  <span className="text-[9px] px-1.5 py-px rounded-full border border-border-def text-text-ter">
                    {grid.mode === 'add' ? '加仓模式' : '底仓模式'}
                  </span>
                )}
                {grid.suitable && (
                  <span className="ml-auto font-mono text-[10px] tabular-nums text-text-sec">
                    {fmtNum(grid.rangeLow)}~{fmtNum(grid.rangeHigh)} 元 · {grid.grids ?? '--'} 格
                  </span>
                )}
              </div>

              {grid.suitable ? (
                <>
                  <div className="mt-1 text-[10px] leading-[1.45] text-text-sec">
                    每格 {grid.sharesPerGrid ?? '--'} 股 / 需 {fmtMoney(grid.capitalPerGrid)} 元
                    {grid.cashNeeded != null && <>，加仓网格共需 {fmtMoney(grid.cashNeeded)} 元</>}
                    {grid.cashAvailable != null && (
                      <>
                        ，账户可用 <span className="text-warn">{fmtMoney(grid.cashAvailable)}</span> 元 ——
                        {grid.cashNeeded != null && grid.cashAvailable < grid.cashNeeded
                          ? ' 现金不足,只能做底仓高抛低吸'
                          : ' 现金够'}
                      </>
                    )}
                    {grid.cashAvailable == null && ' 账户可用资金未填写,按底仓模式'}
                    {grid.stepPct != null && (
                      <>
                        ；步长 {grid.stepPct.toFixed(1)}%
                        {grid.stepPrice != null && `(${grid.stepPrice.toFixed(2)} 元)`}
                      </>
                    )}
                    {grid.netProfitPerGrid != null && (
                      <>
                        ，单格净收益 <span className="text-down">{fmtMoney(grid.netProfitPerGrid)} 元</span>
                        {grid.roundtripFeePct != null && `（往返费率 ${grid.roundtripFeePct.toFixed(3)}%）`}
                      </>
                    )}
                  </div>
                  {decision.concentration?.level === 'high' && grid.mode === 'base' && (
                    <div className="mt-1 text-[10px] leading-[1.45] text-warn">
                      该标的已占持仓成本 {decision.concentration.costSharePct?.toFixed(1)}%
                      ，加仓会放大单一暴露,不给加仓模式
                    </div>
                  )}
                  {grid.risk && (
                    <div className="mt-1 border-t border-dashed border-border-def pt-1 text-[9.5px] leading-[1.45] text-text-ter">
                      <span className="font-semibold text-warn">失效条件</span>:{grid.risk}
                    </div>
                  )}
                </>
              ) : (
                <>
                  <div className="mt-1 text-[10px] leading-[1.45] text-warn">
                    {grid.unsuitableSignals || '当前条件不适合布网格'}
                  </div>
                  {/* 品种费用差异只在 ETF 时补一行(股票的费用影响在下方「费用影响」维度里,不重复) */}
                  {decision.instrumentRule?.kind === 'etf' && decision.costEffect?.note && (
                    <div className="mt-1 text-[9.5px] leading-[1.45] text-text-ter">
                      {decision.costEffect.note.replace(/[;；]\s*$/, '')}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* 白话(AI 解读 / 规则文案 / 现场生成) */}
          {voice && (
            <div
              className="rounded-sm border border-border-def bg-bg-elevated px-2 py-1.5"
              data-testid="advice-voice"
              data-source={voice.source}
            >
              <div className="flex items-center gap-1.5">
                <span className="text-[9px] text-text-ter">{voice.source}</span>
                {voice.time && (
                  <span className="text-[9px] text-text-ter/70">数据时间 {voice.time}</span>
                )}
                {adviceNote && <span className="text-[9px] text-text-ter/70">{adviceNote}</span>}
                <button
                  type="button"
                  onClick={onWriteAdvice}
                  disabled={adviceLoading}
                  data-testid="advice-write-btn"
                  className="ml-auto text-[9.5px] px-2 py-px rounded-sm border border-border-str text-text-sec bg-bg-subtle hover:text-text-pri disabled:opacity-60"
                >
                  {adviceLoading ? '生成中…' : 'AI 写白话'}
                </button>
              </div>
              <div className="mt-1 text-[10.5px] leading-[1.5] text-text-pri">{voice.text}</div>
              {voice.bullets.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {voice.bullets.map((b, i) => (
                    <li key={i} className="text-[10px] leading-[1.45] text-text-sec pl-2 relative">
                      <span className="absolute left-0 text-text-ter">·</span>
                      {b}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* 更多维度(默认收起) */}
          {dims.length > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setShowDims((v) => !v)}
                data-testid="advice-dims-toggle"
                className="text-[9.5px] text-text-ter hover:text-text-sec"
              >
                {showDims ? '▾' : '▸'} 更多维度(成本锚点 / 时间窗口 / 费用影响 / 品种规则 / 集中度)
              </button>
              {showDims && (
                <div className="mt-1" data-testid="advice-dims">
                  {dims.map((dim) => (
                    <div
                      key={dim.key}
                      className="flex gap-2 border-b border-dashed border-border-def/60 py-0.5 last:border-b-0"
                    >
                      <span className="w-[62px] shrink-0 text-[9.5px] text-text-ter">{dim.label}</span>
                      <span className="text-[9.5px] leading-[1.45] text-text-sec">{dim.value}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

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
          {grid?.replaceTPlan && (
            <div className="mt-1 text-[9.5px] leading-[1.4] text-warn">
              已建议配置网格,二者择一,勿同时执行
            </div>
          )}
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
