'use client';

import clsx from 'clsx';

import type {
  AmountTrendResponse,
  AnalysisResult,
  DecisionAdviceText,
  MarketMover,
  Position,
  StockDecision,
} from '@/lib/types';

import { AnalysisPanel, BeginnersGuide } from '@/components/advice/AnalysisPanel';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { DecisionCard } from '@/components/desk/DecisionCard';

/**
 * 决策栏(v0.8 右栏)
 *
 * **为什么右栏是「决策」而不是「更多」**:
 * 旧版把 AI 解读、新手速看、领涨领跌、两市量能分散在页面不同角落,
 * 小白用户要在整页滚动里找「怎么看这只票」。
 * 现在它们固定在右栏,**顺序按「盯盘动作」的思考顺序排**:
 *
 *   0. 操作决策 —— **我现在该干什么**(确定性引擎,置顶)
 *   1. 持仓概览 —— 我现在拿着什么、赚了多少
 *   2. AI 解读 —— 这只票怎么讲
 *   3. 新手速看 —— 我该怎么看(5 步阅读顺序)
 *   4. 领涨 / 领跌 —— 今天是普涨还是个别票在动
 *   5. 两市量能 —— 有没有增量资金
 *
 * 窄屏(<1280px)时这一栏**不隐藏**,而是移到底部横排 ——
 * 它是小白用户的核心入口,不能因为窗口窄就消失。
 */

function fmtY(n: number): string {
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(n: number): string {
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function toneCls(n: number): string {
  if (n > 0) return 'text-up';
  if (n < 0) return 'text-down';
  return 'text-text-ter';
}

export function DecisionColumn({
  positions,
  analysis,
  analysisStarted,
  analysisLoading,
  analysisProgress,
  onRefresh,
  onForceRefresh,
  onRetry,
  gainers,
  losers,
  amountTrend,
  chat,
  decision,
  decisionLoading,
  decisionError,
  decisionAdvice,
  decisionAdviceNote,
  decisionAdviceLoading,
  onWriteDecisionAdvice,
}: {
  positions: Position[];
  analysis: AnalysisResult | null;
  analysisStarted: boolean;
  analysisLoading: boolean;
  analysisProgress: number | null;
  onRefresh: () => void;
  onForceRefresh: () => void;
  onRetry: () => void;
  gainers: MarketMover[];
  losers: MarketMover[];
  amountTrend: AmountTrendResponse['items'];
  /** 确定性决策卡的载荷(与 AI 解读并行拉取,互不阻塞) */
  decision: StockDecision | null;
  decisionLoading: boolean;
  decisionError: string | null;
  /** 决策卡「操作建议」区的现场生成白话(「AI 写白话」按钮触发) */
  decisionAdvice: DecisionAdviceText | null;
  /** 现场生成白话时的降级说明(LLM 不可用 → 退回规则文案) */
  decisionAdviceNote: string | null;
  decisionAdviceLoading: boolean;
  onWriteDecisionAdvice: () => void;
  /** AI 问一问(ChatPanel)所需的当前标的上下文 */
  chat: {
    stockCode: string | null;
    stockName: string | null;
    avgCost: number | null;
    currentPrice: number | null;
    changePct: number | null;
    height: number | null;
    onHeightChange: (h: number) => void;
  };
}) {
  const totals = positions.reduce(
    (acc, p) => {
      acc.marketValue += Number(p.currentPrice ?? 0) * Number(p.shares);
      acc.floating += Number(p.floatingPnl ?? 0);
      acc.today += Number(p.todayPnl ?? 0);
      acc.cost += Number(p.totalCost ?? 0);
      return acc;
    },
    { marketValue: 0, floating: 0, today: 0, cost: 0 },
  );
  const floatPct = totals.cost > 0 ? (totals.floating / totals.cost) * 100 : null;

  const ind = analysis?.indicators ?? null;
  const maxVol = Math.max(...amountTrend.map((i) => i.volumeYi), 1e-9);

  return (
    <div className="flex flex-col min-h-0">
      {/* 0. 操作决策卡(确定性引擎,置顶 —— 用户问的第一个问题是「我现在该干什么」) */}
      <section className="px-3 py-2.5 border-b border-border-def">
        <DecisionCard
          decision={decision}
          loading={decisionLoading}
          error={decisionError}
          analysis={analysis}
          advice={decisionAdvice}
          adviceNote={decisionAdviceNote}
          adviceLoading={decisionAdviceLoading}
          onWriteAdvice={onWriteDecisionAdvice}
        />
      </section>

      {/* 1. 持仓概览 */}
      <section className="px-3 py-2.5 border-b border-border-def">
        <div className="flex items-baseline gap-2 mb-2">
          <span className="text-[11px] font-semibold text-text-pri">持仓概览</span>
          <span className="text-[10px] text-text-ter font-mono">{positions.length} 只</span>
        </div>
        {positions.length === 0 ? (
          <p className="text-[11px] text-text-ter">暂无持仓 —— 下方列表点「设为持仓」即可加入。</p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-1.5">
              <Num label="总市值" value={`¥${fmtY(totals.marketValue)}`} />
              <Num
                label="总浮盈"
                value={floatPct != null ? fmtPct(floatPct) : '--'}
                sub={`¥${fmtY(totals.floating)}`}
                tone={toneCls(totals.floating)}
              />
              <Num
                label="今日盈亏"
                value={`${totals.today >= 0 ? '+' : ''}¥${fmtY(totals.today)}`}
                sub="现价 − 昨收"
                tone={toneCls(totals.today)}
              />
            </div>
            <div className="flex items-center gap-2 mb-0.5 text-[10px] text-text-ter font-mono">
              <span className="flex-1" />
              <span className="shrink-0 w-14 text-right">股数</span>
              <span className="shrink-0 w-14 text-right">成本</span>
              <span className="shrink-0 w-16 text-right">盈亏</span>
            </div>
            <ul className="mt-2">
              {positions.map((p) => {
                const fl = Number(p.floatingPnl ?? 0);
                const cost = Number(p.totalCost ?? 0);
                const pct = cost > 0 ? (fl / cost) * 100 : null;
                const avgCost = p.avgCost != null ? Number(p.avgCost) : null;
                return (
                  <li
                    key={p.stockCode}
                    className="flex items-center gap-2 py-1 border-b border-border-def/40 last:border-b-0 text-[11.5px]"
                  >
                    <span className="text-text-pri truncate min-w-0 flex-1">{p.stockName ?? p.stockCode}</span>
                    <span className="text-text-ter font-mono text-[10px] shrink-0 w-14 text-right">
                      {Number(p.shares)}股
                    </span>
                    <span
                      className="text-text-ter font-mono text-[10px] shrink-0 w-14 text-right"
                      title="摊薄成本价(券商口径)"
                    >
                      {avgCost != null ? avgCost.toFixed(3) : '--'}
                    </span>
                    <span
                      className={clsx(
                        'font-mono tabular-nums shrink-0 w-16 text-right',
                        toneCls(fl),
                      )}
                    >
                      {pct != null ? fmtPct(pct) : '--'}
                    </span>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </section>

      {/* 2. AI 解读 */}
      <section className="px-3 py-2.5 border-b border-border-def">
        <div className="flex items-baseline gap-2 mb-2">
          <span className="text-[11px] font-semibold text-text-pri">AI 解读</span>
          {analysis?.ai && (
            <span
              className={clsx(
                'ml-auto text-[10px] font-mono px-1.5 py-px rounded-sm border',
                analysis.ai.view === 'bullish'
                  ? 'text-up border-up/40 bg-up-bg'
                  : analysis.ai.view === 'bearish'
                    ? 'text-down border-down/40 bg-down-bg'
                    : 'text-text-ter border-border-def bg-bg-subtle',
              )}
            >
              {analysis.ai.view === 'bullish' ? '看多' : analysis.ai.view === 'bearish' ? '看空' : '中性'}
            </span>
          )}
        </div>
        <AnalysisPanel
          analysis={analysis}
          started={analysisStarted}
          loading={analysisLoading}
          aiProgress={analysisProgress}
          onRefresh={onRefresh}
          onForceRefresh={onForceRefresh}
          onRetry={onRetry}
          showBeginners={false}
        />
      </section>

      {/* 3. 新手速看 */}
      <section className="px-3 py-2.5 border-b border-border-def">
        <div className="flex items-baseline gap-2 mb-2">
          <span className="text-[11px] font-semibold text-text-pri">新手速看 · 5 步</span>
          {ind && <span className="ml-auto text-[10px] text-accent">已分析</span>}
        </div>
        <BeginnersGuide
          signal={ind?.signal}
          volumeRatio={ind?.volume?.ratio ?? null}
          position={ind?.position}
        />
      </section>

      {/* 4. 领涨 / 领跌 */}
      <section className="px-3 py-2.5 border-b border-border-def">
        <div className="flex items-baseline gap-2 mb-1.5">
          <span className="text-[11px] font-semibold text-text-pri">领涨 / 领跌</span>
        </div>
        <MoverList title="领涨" items={gainers} tone="up" />
        <MoverList title="领跌" items={losers} tone="down" />
      </section>

      {/* 5. 两市量能 */}
      <section className="px-3 py-2.5 border-b border-border-def">
        <div className="flex items-baseline gap-2 mb-1.5">
          <span className="text-[11px] font-semibold text-text-pri">两市量能 · 近 5 日</span>
          <span className="ml-auto text-[10px] text-text-ter font-mono">亿手</span>
        </div>
        {amountTrend.length > 0 ? (
          <>
            <div className="flex items-end gap-1.5 h-12" aria-hidden>
              {amountTrend.map((it) => (
                <div
                  key={it.date}
                  className="flex-1 h-full flex items-end"
                  title={`${it.date} ${it.volumeYi.toFixed(0)} 亿手`}
                >
                  <div
                    className="w-full rounded-t-xs bg-accent/35"
                    style={{ height: `${Math.max((it.volumeYi / maxVol) * 100, 6)}%` }}
                  />
                </div>
              ))}
            </div>
            <div className="flex justify-between text-[9px] text-text-ter font-mono mt-0.5">
              {amountTrend.map((it) => (
                <span key={it.date}>{it.date.slice(5)}</span>
              ))}
            </div>
          </>
        ) : (
          <div className="h-12 rounded-md bg-bg-elevated animate-pulse" />
        )}
      </section>

      {/* 6. AI 问一问 */}
      <section className="px-3 py-2.5">
        <div className="flex items-baseline gap-2 mb-1.5">
          <span className="text-[11px] font-semibold text-text-pri">AI 问一问</span>
          <span className="text-[10px] text-text-ter">就这只票提问</span>
        </div>
        <ChatPanel
          stockCode={chat.stockCode}
          stockName={chat.stockName}
          avgCost={chat.avgCost}
          currentPrice={chat.currentPrice}
          changePct={chat.changePct}
          height={chat.height}
          onHeightChange={chat.onHeightChange}
        />
      </section>
    </div>
  );
}

function Num({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span className="text-[9px] text-text-ter font-mono tracking-wider truncate">{label}</span>
      <span
        className={clsx(
          'text-[12.5px] font-mono font-semibold tabular-nums truncate',
          tone ?? 'text-text-pri',
        )}
      >
        {value}
      </span>
      {sub && <span className="text-[9.5px] text-text-ter truncate">{sub}</span>}
    </div>
  );
}

function MoverList({
  title,
  items,
  tone,
}: {
  title: string;
  items: MarketMover[];
  tone: 'up' | 'down';
}) {
  return (
    <div className="mb-1.5 last:mb-0">
      <div className="flex items-center gap-1.5 mb-0.5">
        <span
          className={clsx('w-1.5 h-1.5 rounded-full', tone === 'up' ? 'bg-up' : 'bg-down')}
          aria-hidden
        />
        <span className="text-[9.5px] text-text-ter font-mono tracking-wider">{title}</span>
      </div>
      {items.length === 0 ? (
        <div className="h-4 rounded-sm bg-bg-elevated animate-pulse" />
      ) : (
        <ul>
          {items.slice(0, 3).map((m) => (
            <li
              key={m.code}
              className="flex items-center gap-2 text-[11.5px] leading-[1.5] min-w-0"
            >
              <span className="text-text-pri truncate min-w-0 flex-1">{m.name}</span>
              <span
                className={clsx(
                  'font-mono tabular-nums shrink-0',
                  tone === 'up' ? 'text-up' : 'text-down',
                )}
              >
                {m.changePct > 0 ? '+' : ''}
                {m.changePct.toFixed(2)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
