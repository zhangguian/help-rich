'use client';

import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import clsx from 'clsx';

import { GlassCard } from '@/components/ui/GlassCard';
import { Button } from '@/components/ui/Button';
import { TermHint } from '@/components/ui/TermHint';
import type {
  AnalysisResult,
  SignalFusion,
  SignalWinrate,
  LiarIndicator,
  PatternMatch,
  VolumePriceIndicator,
  BollIndicator,
  KdjIndicator,
  MacdIndicator,
  PositionIndicator,
} from '@/lib/types';

const VIEW_META = {
  bullish: { label: '看多', cls: 'text-up border-up/40 bg-up-bg' },
  bearish: { label: '看空', cls: 'text-down border-down/40 bg-down-bg' },
  neutral: { label: '中性', cls: 'text-text-sec border-border-def bg-bg-subtle' },
};

const CHANNEL_META = {
  up: { label: '上涨通道', cls: 'text-up' },
  down: { label: '下降通道', cls: 'text-down' },
  sideways: { label: '震荡整理', cls: 'text-text-sec' },
};

const VOLUME_META = {
  expand: { label: '放量', cls: 'text-up' },
  shrink: { label: '缩量', cls: 'text-down' },
  normal: { label: '量能正常', cls: 'text-text-sec' },
};

const SIGNAL_VIEW_META = {
  bullish: { label: '看多', cls: 'text-up border-up/40 bg-up-bg' },
  bearish: { label: '看空', cls: 'text-down border-down/40 bg-down-bg' },
  neutral: { label: '中性', cls: 'text-text-sec border-border-def bg-bg-subtle' },
};

const CONFIDENCE_META = {
  high: { label: '高置信度', cls: 'text-accent' },
  medium: { label: '中置信度', cls: 'text-text-pri' },
  low: { label: '低置信度', cls: 'text-text-ter' },
};

/**
 * 右侧上栏 · 操作提示(roadmap 功能3/4 + K线智能分析 v1)
 *
 * 顶部置顶「机械信号」卡(确定性引擎结论:view/score/confidence/reasons),与下方
 * 「AI 分析」卡(LLM 白话解读)两个层面并存。
 *
 * 技术指标卡片:通道、量能、均线、支撑/压力、企稳(原 v0.4-roadmap),新增
 * MACD/KDJ/BOLL/量价/形态/诱多诱空/位置评估。
 */
export function AnalysisPanel({
  analysis,
  started,
  loading,
  aiProgress,
  onRefresh,
  onForceRefresh,
  onRetry,
  showBeginners = true,
}: {
  analysis: AnalysisResult | null;
  started: boolean;
  loading: boolean;
  /** 流式进度秒数(LLM 启动后 ≥ 30s 才有);用于「思考中…Ns」展示 */
  aiProgress?: number | null;
  onRefresh: () => void;
  onForceRefresh?: () => void;
  onRetry?: () => void;
  /**
   * v0.8 交易台:右栏把「新手速看」拆成独立区块(见 components/desk/DecisionColumn.tsx),
   * 所以这里允许关掉内嵌的那一份,避免同一屏出现两张新手速看。
   * 其他页面(深度分析页等)默认仍然内嵌,行为不变。
   */
  showBeginners?: boolean;
}) {
  const ind = analysis?.indicators;

  return (
    <div className="space-y-3">
      {/* M3.1 新手速看卡:5 步阅读顺序(给小白的第一眼指引) */}
      {showBeginners && (
        <BeginnersGuide
          signal={ind?.signal}
          volumeRatio={ind?.volume.ratio ?? null}
          position={ind?.position}
        />
      )}
      {/* 顶部置顶:机械信号卡(确定性引擎,与 AI 卡并存) */}
      {ind && (
        <SignalPanel
          signal={ind.signal}
          winrate={analysis?.signalWinrate}
          volumePrice={ind.volumePrice}
          liar={ind.liar}
          position={ind.position}
          patterns={ind.patterns}
        />
      )}
      {/* M1.2 买卖位置参考卡:近 120 日 P20/P80 风险带 + 参考支撑 + 建议止损 */}
      {ind && (
        <PositionRiskCard
          position={ind.position}
          currentPrice={
            analysis?.currentPrice != null
              ? Number(analysis.currentPrice)
              : null
          }
        />
      )}

      {/* AI 分析卡(LLM 白话解读) */}
      <GlassCard padding="md" className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold text-text-pri">✨ AI 分析</span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" onClick={onRefresh} disabled={loading} className='text-xs'>
              {loading
                ? aiProgress != null
                  ? `⏳ AI 思考中…(${aiProgress}s)`
                  : '分析中…'
                : started
                  ? '🔄 重新分析'
                  : '✨ 开始分析'}
            </Button>
            {started && onForceRefresh && (
              <Button
                variant="ghost"
                size="sm"
                className='text-xs'
                onClick={onForceRefresh}
                disabled={loading}
                title="清空本地缓存 + 后端节点缓存,强制 LLM 重新解读(会消耗 token)"
              >
                ⚡ 强制重算
              </Button>
            )}
          </div>
        </div>

        {/* 数据截至 + 现价(盘中实时 vs K 线收盘) */}
        {analysis && (
          <div className="flex items-center justify-between text-xs text-text-ter">
            <span>
              📅 数据截至 {analysis.latestKlineDate ?? '—'} 收盘
              {analysis.currentPrice && Number(analysis.currentPrice) !== ind?.latestClose && (
                <span className="text-up ml-2">
                  · 实时 ¥{analysis.currentPrice}
                </span>
              )}
            </span>
          </div>
        )}

        <AnimatePresence mode="wait">
          {loading ? (
            <motion.div key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="h-4 w-24 rounded bg-border-def animate-pulse" />
              <div className="h-3 w-full rounded bg-bg-subtle animate-pulse mt-3" />
              <div className="h-3 w-5/6 rounded bg-bg-subtle animate-pulse mt-2" />
            </motion.div>
          ) : analysis?.ai ? (
            <motion.div
              key="ai"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="space-y-3"
            >
              <div className="flex flex-col items-start gap-2">
                <span
                  className={clsx(
                    'px-3 py-1 rounded-full text-sm font-semibold border',
                    (VIEW_META[analysis.ai.view] ?? VIEW_META.neutral).cls,
                  )}
                >
                  {(VIEW_META[analysis.ai.view] ?? VIEW_META.neutral).label}
                </span>
                <span className="text-sm text-text-sec">{analysis.ai.viewReason}</span>
              </div>
              <p className="text-sm text-text-sec leading-relaxed whitespace-pre-wrap">{analysis.ai.trend}</p>
              <p className="text-sm text-text-sec leading-relaxed whitespace-pre-wrap">{analysis.ai.volumeNote}</p>
              {analysis.ai.keyLevels.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {analysis.ai.keyLevels.map((lvl, i) => (
                    <span
                      key={i}
                      className="text-xs px-2 py-1 rounded-lg bg-bg-subtle border border-border-def text-text-sec font-mono"
                      title={lvl.note}
                    >
                      {lvl.type === 'support' ? '支撑' : lvl.type === 'pressure' ? '压力' : '企稳'}{' '}
                      {lvl.price}
                    </span>
                  ))}
                </div>
              )}
              <OperationAdviceBlock analysis={analysis} />
              <div className="text-xs text-text-ter leading-relaxed bg-warn-bg/30 border border-warn/20 rounded-lg p-3 space-y-1.5 whitespace-pre-wrap">
                <p className="font-semibold text-warn">⚠ 风险提示</p>
                <p>{analysis.ai.riskWarning}</p>
              </div>
            </motion.div>
          ) : started ? (
            <motion.div
              key="noai"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-2"
            >
              <p className="text-sm font-medium text-red-500">
                {analysis?.aiError === 'timeout'
                  ? 'AI 解读超时,请点重试'
                  : analysis?.aiError === 'unconfigured'
                    ? '未配置 LLM Key,请联系管理员'
                    : analysis?.aiError === 'failed'
                      ? 'AI 解析失败,请点重试'
                      : 'AI 暂不可用,请点重试'}
              </p>
              <p className="text-xs text-text-ter">以下为当前纯技术指标。</p>
              <Button variant="ghost" size="sm" onClick={onRetry ?? onRefresh} disabled={loading}>
                🔄 重试
              </Button>
            </motion.div>
          ) : (
            <motion.p
              key="idle"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-sm text-text-ter"
            >
              点击上方「✨ 开始分析」,AI 结合技术指标给你白话解读。
            </motion.p>
          )}
        </AnimatePresence>
      </GlassCard>

      {/* 技术指标面板 */}
      <GlassCard padding="md" className="space-y-4">
        <span className="text-sm font-semibold text-text-pri">📊 技术指标</span>
        {!ind ? (
          <p className="text-sm text-text-ter">选择左侧股票后显示指标</p>
        ) : (
          <div className="space-y-4">
            {/* 通道 */}
            <div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-text-sec inline-flex items-center">
                  通道<TermHint term="channel" />
                </span>
                <span className={clsx('font-semibold', CHANNEL_META[ind.channel.state].cls)}>
                  {CHANNEL_META[ind.channel.state].label}
                </span>
              </div>
              <p className="text-xs text-text-ter mt-1">
                上轨 <span className="font-mono">{ind.channel.upper ?? '--'}</span> · 下轨{' '}
                <span className="font-mono">{ind.channel.lower ?? '--'}</span>
              </p>
            </div>

            {/* 量比 */}
            <div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-text-sec inline-flex items-center">
                  量能<TermHint term="volume" />
                </span>
                <span
                  className={clsx(
                    'font-semibold',
                    VOLUME_META[ind.volume.state ?? 'normal']?.cls ?? 'text-text-sec',
                  )}
                >
                  {ind.volume.ratio != null
                    ? `${VOLUME_META[ind.volume.state ?? 'normal']?.label ?? '量能正常'} ${ind.volume.ratio.toFixed(2)}`
                    : '数据不足'}
                </span>
              </div>
              <p className="text-xs text-text-ter mt-1">
                近5日均量 ÷ 前20日均量(≥1.5 放量,≤0.7 缩量)
              </p>
            </div>

            {/* 均线 */}
            <div>
              <div className="text-sm text-text-sec mb-1.5 inline-flex items-center">
                均线<TermHint term="ma" />
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {(['ma5', 'ma10', 'ma20', 'ma60'] as const).map((k) => (
                  <div key={k} className="rounded-lg bg-bg-subtle px-2 py-1.5">
                    <div className="text-[10px] text-text-ter uppercase">{k}</div>
                    <div className="text-sm font-mono text-text-pri">{ind.ma[k] ?? '--'}</div>
                  </div>
                ))}
              </div>
            </div>

            <MacdCard macd={ind.macd} />
            <KdjCard kdj={ind.kdj} />
            <BollCard boll={ind.boll} />

            {/* 量价四维 */}
            <VolumePriceCard vp={ind.volumePrice} />

            {/* 形态 */}
            <PatternsCard patterns={ind.patterns} />

            {/* 诱多诱空 */}
            <LiarCard liar={ind.liar} />

            {/* 位置评估 */}
            <PositionCard position={ind.position} />

            {/* 支撑 / 压力 */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <div className="text-xs text-text-ter mb-1 inline-flex items-center">
                  支撑位<TermHint term="support" />
                </div>
                <div className="flex flex-wrap gap-1">
                  {ind.supportPressure.support.length === 0 && (
                    <span className="text-xs text-text-ter">暂无</span>
                  )}
                  {ind.supportPressure.support.map((p) => (
                    <span
                      key={p}
                      className="text-xs font-mono px-1.5 py-0.5 rounded bg-down-bg text-down"
                    >
                      {p}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-xs text-text-ter mb-1 inline-flex items-center">
                  压力位<TermHint term="pressure" />
                </div>
                <div className="flex flex-wrap gap-1">
                  {ind.supportPressure.pressure.length === 0 && (
                    <span className="text-xs text-text-ter">暂无</span>
                  )}
                  {ind.supportPressure.pressure.map((p) => (
                    <span
                      key={p}
                      className="text-xs font-mono px-1.5 py-0.5 rounded bg-up-bg text-up"
                    >
                      {p}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* 企稳 */}
            <div className="rounded-xl bg-bg-subtle p-3 space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-text-sec inline-flex items-center">
                  企稳点<TermHint term="stabilize" />
                </span>
                <span
                  className={clsx(
                    'font-semibold',
                    ind.stabilize.state ? 'text-accent' : 'text-text-ter',
                  )}
                >
                  {ind.stabilize.state ? '已企稳 ✓' : '未企稳'}
                  {ind.stabilize.price != null && (
                    <span className="font-mono text-text-pri"> {ind.stabilize.price}</span>
                  )}
                </span>
              </div>
              {ind.stabilize.reasons.map((r) => (
                <div key={r.name} className="flex flex-col gap-2 text-xs">
                  <div className="flex items-center gap-2 text-xs">
                    <span className={r.ok ? 'text-accent' : 'text-text-ter'}>
                      {r.ok ? '✓' : '✗'}
                    </span>
                    <span className="text-text-sec">{r.name}</span>
                  </div>
                  <div className="text-text-ter font-mono">{r.note}</div>
                </div>
              ))}
              <p className="text-xs text-text-ter">
                站住企稳点不破,可视为多头占优;跌破则谨慎
              </p>
            </div>
          </div>
        )}
      </GlassCard>
    </div>
  );
}

// ============================================================
// 机械信号卡(确定性引擎 · 顶部置顶)
// ============================================================

/** M1.3 信号历史胜率回检:历史同向信号出现 N 次,5/20 日后上涨概率 */
function SignalWinrateBlock({ winrate }: { winrate: SignalWinrate }) {
  const pct = (v: number) => `${(v * 100).toFixed(0)}%`;
  const tone = (v: number) => (v >= 0.6 ? 'text-up' : v <= 0.4 ? 'text-down' : 'text-text-sec');
  if (winrate.insufficient) {
    return (
      <div className="rounded-lg bg-bg-subtle px-3 py-2 text-xs text-text-ter">
        {winrate.signalLabel}信号出现过 {winrate.count} 次,样本太少,暂不统计胜率
        (至少 3 次才有参考价值)
      </div>
    );
  }
  return (
    <div className="rounded-lg bg-bg-subtle px-3 py-2 space-y-1">
      <div className="text-xs text-text-ter">
        历史回测:近 120 个交易日内,「{winrate.signalLabel}」信号共出现 {winrate.sample5} 次
      </div>
      <div className="flex items-center gap-3 text-xs">
        <span className="text-text-ter">5日后上涨率</span>
        <span className={clsx('font-semibold font-mono', tone(winrate.up5))}>
          {pct(winrate.up5)}
        </span>
        <span className="text-text-ter">20日后上涨率</span>
        <span className={clsx('font-semibold font-mono', tone(winrate.up20))}>
          {pct(winrate.up20)}
        </span>
      </div>
      <p className="text-[11px] text-text-ter">仅为历史统计,不构成收益承诺;样本越少参考意义越弱</p>
    </div>
  );
}

function SignalPanel({
  signal,
  winrate,
  volumePrice,
  liar,
  position,
  patterns,
}: {
  signal: SignalFusion | undefined;
  winrate: SignalWinrate | undefined;
  volumePrice: VolumePriceIndicator;
  liar: LiarIndicator;
  position: PositionIndicator;
  patterns: PatternMatch[];
}) {
  // 旧缓存(24h IndexedDB)可能不含 signal 字段,降级显示而不崩溃
  if (!signal) {
    return (
      <GlassCard padding="md" className="space-y-3 border border-accent/20">
        <span className="text-sm font-semibold text-text-pri">🤖 机械信号 · 确定性引擎</span>
        <p className="text-sm text-text-ter">
          旧缓存数据(不含机械信号),点击下方「✨ 开始分析」刷新即可看到
        </p>
      </GlassCard>
    );
  }
  const view = SIGNAL_VIEW_META[signal.view] ?? SIGNAL_VIEW_META.neutral;
  const conf = CONFIDENCE_META[signal.confidence] ?? CONFIDENCE_META.medium;

  return (
    <GlassCard padding="md" className="space-y-3 border border-accent/20">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-text-pri">🤖 机械信号 · 确定性引擎</span>
        <span className={clsx('text-xs', conf.cls)}>{conf.label}</span>
      </div>

      <div className="flex items-center gap-2">
        <span
          className={clsx(
            'px-3 py-1 rounded-full text-sm font-semibold border',
            view.cls,
          )}
        >
          {view.label} · {signal.score}
        </span>
        <span className="text-xs text-text-sec">基于指标规则,可解释</span>
      </div>

      <p className="text-xs text-text-sec leading-relaxed">{signal.summary}</p>

      {/* M1.3 信号历史胜率回检 */}
      {winrate && <SignalWinrateBlock winrate={winrate} />}

      {/* reasons */}
      <div className="space-y-1">
        {signal.reasons.slice(0, 4).map((r, i) => (
          <div
            key={i}
            className="flex items-center gap-2 text-xs"
            title={`权重 ${r.weight}`}
          >
            <span
              className={clsx(
                'font-mono w-8 text-right',
                r.delta > 0 ? 'text-up' : r.delta < 0 ? 'text-down' : 'text-text-ter',
              )}
            >
              {r.delta > 0 ? '+' : ''}
              {r.delta}
            </span>
            <span className="text-text-sec shrink-0">{r.module}</span>
            <span className="text-text-pri truncate">{r.verdict}</span>
          </div>
        ))}
      </div>

      {/* 量价 + 诱多诱空 + 位置 + 形态 紧凑摘要 */}
      <div className="flex flex-wrap gap-1.5 pt-1 border-t border-border-def">
        {volumePrice.label && (
          <span
            className={clsx(
              'text-xs px-2 py-0.5 rounded-full border',
              volumePrice.direction === 'healthy_up'
                ? 'text-up border-up/30'
                : volumePrice.direction === 'liar_up_suspect' || volumePrice.direction === 'panic_sell'
                  ? 'text-down border-down/30'
                  : 'text-text-sec border-border-def',
            )}
          >
            {volumePrice.emoji} {volumePrice.label}
          </span>
        )}
        {liar.bullLiars.length > 0 && (
          <span className="text-xs px-2 py-0.5 rounded-full border border-yellow-400/40 text-yellow-600">
            ⚠️ 诱多 {liar.bullLiars.length} 类
          </span>
        )}
        {liar.bearLiars.length > 0 && (
          <span className="text-xs px-2 py-0.5 rounded-full border border-blue-400/40 text-blue-600">
            🪤 诱空 {liar.bearLiars.length} 类
          </span>
        )}
        {position.band !== 'mid' && (
          <span
            className={clsx(
              'text-xs px-2 py-0.5 rounded-full border',
              position.band === 'high'
                ? 'text-warn border-warn/40'
                : 'text-accent border-accent/40',
            )}
          >
            {position.band === 'high' ? '🔺 高位' : '🔻 低位'}
          </span>
        )}
        {patterns.slice(0, 2).map((p, i) => (
          <span
            key={i}
            className={clsx(
              'text-xs px-2 py-0.5 rounded-full border',
              p.type === 'bull'
                ? 'text-up border-up/30'
                : p.type === 'bear'
                  ? 'text-down border-down/30'
                  : 'text-text-sec border-border-def',
            )}
          >
            {p.emoji} {p.name}
          </span>
        ))}
      </div>
    </GlassCard>
  );
}

// ============================================================
// 副指标卡片(旧缓存可能缺失新字段,统一降级)
// ============================================================

function MissingHint({ label }: { label: string }) {
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-text-sec">{label}</span>
        <span className="text-xs text-text-ter">旧缓存数据,需刷新</span>
      </div>
    </div>
  );
}

function MacdCard({ macd }: { macd: MacdIndicator | undefined }) {
  if (!macd) return <MissingHint label="MACD (12,26,9)" />;
  const cross = macd.cross;
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-text-sec inline-flex items-center">
          MACD (12,26,9)<TermHint term="macd" />
        </span>
        {cross && (
          <span
            className={clsx(
              'text-xs font-semibold',
              cross === 'golden' ? 'text-up' : 'text-down',
            )}
          >
            {cross === 'golden' ? '🔺 金叉' : '🔻 死叉'}
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-1.5 mt-1.5">
        <Mini label="DIF" value={macd.dif} />
        <Mini label="DEA" value={macd.dea} />
        <Mini label="HIST" value={macd.hist} />
      </div>
    </div>
  );
}

function KdjCard({ kdj }: { kdj: KdjIndicator | undefined }) {
  if (!kdj) return <MissingHint label="KDJ (9)" />;
  const zoneMeta =
    kdj.zone === 'overbought'
      ? { label: '超买', cls: 'text-down' }
      : kdj.zone === 'oversold'
        ? { label: '超卖', cls: 'text-up' }
        : { label: '正常', cls: 'text-text-sec' };
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-text-sec inline-flex items-center">
          KDJ (9)<TermHint term="kdj" />
        </span>
        <span className={clsx('text-xs font-semibold', zoneMeta.cls)}>{zoneMeta.label}</span>
      </div>
      <div className="grid grid-cols-3 gap-1.5 mt-1.5">
        <Mini label="K" value={kdj.k} />
        <Mini label="D" value={kdj.d} />
        <Mini label="J" value={kdj.j} />
      </div>
    </div>
  );
}

function BollCard({ boll }: { boll: BollIndicator | undefined }) {
  if (!boll) return <MissingHint label="BOLL (20,2)" />;
  const posMeta =
    boll.position === 'touching_upper'
      ? { label: '触上轨', cls: 'text-yellow-600' }
      : boll.position === 'touching_lower'
        ? { label: '触下轨', cls: 'text-blue-600' }
        : { label: '中轨', cls: 'text-text-sec' };
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-text-sec inline-flex items-center">
          BOLL (20,2)<TermHint term="boll" />
        </span>
        <div className="flex items-center gap-2">
          {boll.squeeze && (
            <span className="text-xs font-semibold text-warn">⚠️ 收口</span>
          )}
          <span className={clsx('text-xs font-semibold', posMeta.cls)}>{posMeta.label}</span>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-1.5 mt-1.5">
        <Mini label="上轨" value={boll.upper} />
        <Mini label="中轨" value={boll.mid} />
        <Mini label="下轨" value={boll.lower} />
      </div>
      {boll.bandwidth != null && (
        <p className="text-xs text-text-ter mt-1">带宽 {boll.bandwidth.toFixed(2)}%</p>
      )}
    </div>
  );
}

function VolumePriceCard({ vp }: { vp: VolumePriceIndicator | undefined }) {
  if (!vp) return <MissingHint label="量价四维" />;
  const dirMeta =
    vp.direction === 'healthy_up'
      ? { cls: 'text-up' }
      : vp.direction === 'panic_sell' || vp.direction === 'liar_up_suspect'
        ? { cls: 'text-down' }
        : { cls: 'text-text-sec' };
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-text-sec inline-flex items-center">
          量价四维<TermHint term="volume-price" />
        </span>
        <span className={clsx('font-semibold text-sm', dirMeta.cls)}>
          {vp.emoji} {vp.label ?? '数据不足'}
        </span>
      </div>
      {vp.reasons.map((r, i) => (
        <div key={i} className="text-xs text-text-ter mt-1 font-mono">
          {r.note}
        </div>
      ))}
    </div>
  );
}

function PatternsCard({ patterns }: { patterns: PatternMatch[] | undefined }) {
  if (!patterns) return <MissingHint label="形态识别" />;
  if (patterns.length === 0) {
    return (
      <div>
        <div className="flex items-center justify-between text-sm">
          <span className="text-text-sec inline-flex items-center">
            形态识别<TermHint term="pattern" />
          </span>
          <span className="text-xs text-text-ter">近期未出现典型形态</span>
        </div>
      </div>
    );
  }
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-text-sec inline-flex items-center">
          形态识别<TermHint term="pattern" />
        </span>
        <span className="text-xs text-text-ter">{patterns.length} 项</span>
      </div>
      <div className="flex flex-wrap gap-1.5 mt-1.5">
        {patterns.map((p, i) => (
          <span
            key={i}
            className={clsx(
              'text-xs px-2 py-0.5 rounded-full border',
              p.type === 'bull'
                ? 'text-up border-up/30'
                : p.type === 'bear'
                  ? 'text-down border-down/30'
                  : 'text-text-sec border-border-def',
            )}
          >
            {p.emoji} {p.name}
            {/* canvas 上的标记不可聚焦,这里补一个「?」让键盘用户也能查到同样的解释 */}
            <TermHint term={p.name} />
          </span>
        ))}
      </div>
    </div>
  );
}

function LiarCard({ liar }: { liar: LiarIndicator | undefined }) {
  if (!liar) return <MissingHint label="诱多诱空" />;
  if (liar.bullLiars.length === 0 && liar.bearLiars.length === 0) {
    return (
      <div>
        <div className="flex items-center justify-between text-sm">
          <span className="text-text-sec inline-flex items-center">
            诱多诱空<TermHint term="liar" />
          </span>
          <span className="text-xs text-text-ter">{liar.summary}</span>
        </div>
      </div>
    );
  }
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-text-sec inline-flex items-center">
          诱多诱空<TermHint term="liar" />
        </span>
        <span className="text-xs text-text-ter">{liar.summary}</span>
      </div>
      <div className="space-y-1.5 mt-1.5">
        {liar.bullLiars.map((p, i) => (
          <div
            key={`b${i}`}
            className="rounded-lg bg-yellow-500/10 border border-yellow-500/20 p-2 text-xs"
          >
            <div className="font-semibold text-yellow-600 mb-0.5">⚠️ {p.name}</div>
            <div className="text-text-sec font-mono">{p.note}</div>
          </div>
        ))}
        {liar.bearLiars.map((p, i) => (
          <div
            key={`B${i}`}
            className="rounded-lg bg-blue-500/10 border border-blue-500/20 p-2 text-xs"
          >
            <div className="font-semibold text-blue-600 mb-0.5">🪤 {p.name}</div>
            <div className="text-text-sec font-mono">{p.note}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PositionCard({ position }: { position: PositionIndicator | undefined }) {
  if (!position) return <MissingHint label="位置评估" />;
  const bandMeta =
    position.band === 'high'
      ? { label: '高位(谨慎)', cls: 'text-warn' }
      : position.band === 'low'
        ? { label: '低位(关注)', cls: 'text-accent' }
        : { label: '中位', cls: 'text-text-sec' };
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-text-sec inline-flex items-center">
          位置评估<TermHint term="position" />
        </span>
        <span className={clsx('text-xs font-semibold', bandMeta.cls)}>{bandMeta.label}</span>
      </div>
      <div className="grid grid-cols-3 gap-1.5 mt-1.5">
        <Mini label="20日%" value={position.pct20} suffix="%" />
        <Mini label="60日%" value={position.pct60} suffix="%" />
        <Mini label="MA60偏%" value={position.biasMa60} suffix="%" />
      </div>
      {position.rangePct != null && (
        <p className="text-xs text-text-ter mt-1">
          近 250 日高低分位 {position.rangePct.toFixed(0)}%
        </p>
      )}
      {/* v0.5 M1.2 风险带详情已上移至顶部 PositionRiskCard */}
    </div>
  );
}

/**
 * M1.2 买卖位置参考卡(roadmap §4 M1.2)
 *
 * 显示近 120 日 P20/P80 风险带:
 *  - 高位区间 = 当前价 ≥ P80
 *  - 中位区间 = P20 ≤ 当前价 < P80
 *  - 低位区间 = 当前价 < P20
 *
 * 附带:参考支撑价(近 20 日最低 × 0.98)、建议止损价(支撑 × 0.97)
 * 数据全部由 ta_service._position 计算,前端仅展示
 */
function PositionRiskCard({
  position,
  currentPrice,
}: {
  position: PositionIndicator;
  currentPrice: number | null;
}) {
  const band = position.riskBand ?? 'mid';
  const BAND_META: Record<
    'high' | 'mid' | 'low',
    { label: string; chipCls: string; hint: string; color: string }
  > = {
    high: {
      label: '高位风险区',
      chipCls: 'text-warn border-warn/40 bg-warn-bg/40',
      hint: '当前处于近 120 日高位区间,追涨风险偏高,注意止盈/减仓节奏',
      color: 'bg-warn',
    },
    mid: {
      label: '中位观察区',
      chipCls: 'text-text-sec border-border-def bg-bg-subtle',
      hint: '当前处于近 120 日中位区间,结合量价与下方机械信号再做判断',
      color: 'bg-accent',
    },
    low: {
      label: '低位机会区',
      chipCls: 'text-accent border-accent/40 bg-accent-bg/40',
      hint: '当前处于近 120 日低位区间,注意是否趋势下行,不宜盲目抄底',
      color: 'bg-accent',
    },
  };
  const meta = BAND_META[band];

  const p20 = position.p20 ?? null;
  const p80 = position.p80 ?? null;
  const cur =
    currentPrice != null
      ? Number(currentPrice)
      : null;
  const hasBand = p20 != null && p80 != null && p80 > (p20 as number);
  const pctInBand =
    hasBand && cur != null
      ? Math.max(0, Math.min(100, ((cur - (p20 as number)) / ((p80 as number) - (p20 as number))) * 100))
      : null;
  const stopAbove = (v: number) => hasBand && cur != null && cur >= v;

  return (
    <GlassCard padding="md" className="space-y-3 border border-border-def">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-text-pri inline-flex items-center">
          📍 买卖位置参考<TermHint term="position_band" />
        </span>
        <span
          className={clsx(
            'text-xs px-2 py-0.5 rounded-full border font-semibold',
            meta.chipCls,
          )}
        >
          {meta.label}
        </span>
      </div>
      <p className="text-xs text-text-sec leading-relaxed">{meta.hint}</p>

      {/* P20 - P80 位置条 */}
      {hasBand && (
        <div>
          <div className="relative h-2 rounded-full bg-gradient-to-r from-accent/30 via-text-ter/15 to-warn/30 overflow-hidden">
            {pctInBand != null && (
              <div
                className={clsx(
                  'absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full ring-2 ring-bg-pri shadow-md',
                  band === 'high' ? 'bg-warn' : band === 'mid' ? 'bg-accent' : 'bg-accent',
                )}
                style={{ left: `calc(${pctInBand}% - 6px)` }}
                title={`当前价 ¥${cur?.toFixed(2)}`}
              />
            )}
          </div>
          <div className="flex justify-between text-[10px] text-text-ter font-mono mt-1">
            <span>P20 ¥{p20.toFixed(2)}</span>
            <span>P80 ¥{p80.toFixed(2)}</span>
          </div>
        </div>
      )}

      {/* 参考支撑 + 建议止损 */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-xl bg-bg-subtle px-3 py-2">
          <div className="text-[10px] text-text-ter">参考支撑(近 20 日最低 × 0.98)</div>
          <div className="text-base font-mono text-text-pri mt-0.5">
            {position.supportPrice != null ? (
              `¥${position.supportPrice.toFixed(2)}`
            ) : (
              <span className="text-text-ter text-xs">数据不足</span>
            )}
          </div>
          {position.supportPrice != null && stopAbove(position.supportPrice) && (
            <div className="text-[10px] text-up mt-0.5">现价高于支撑 ✓</div>
          )}
        </div>
        <div className="rounded-xl bg-bg-subtle px-3 py-2">
          <div className="text-[10px] text-text-ter">建议止损(支撑 × 0.97)</div>
          <div className="text-base font-mono text-down mt-0.5">
            {position.stopLossPrice != null ? (
              `¥${position.stopLossPrice.toFixed(2)}`
            ) : (
              <span className="text-text-ter text-xs">数据不足</span>
            )}
          </div>
          {position.stopLossPrice != null && stopAbove(position.stopLossPrice) && (
            <div className="text-[10px] text-text-ter mt-0.5">跌破请考虑减仓</div>
          )}
        </div>
      </div>
    </GlassCard>
  );
}

/**
 * M3.1 新手速看卡(roadmap §4 M3.1)
 *
 * 5 步阅读顺序,让小白知道"先看什么后看什么":
 *  方向 → 量能 → 价位 → 位置 → 信号
 *
 * 每步带一个基于当前股票实际数据的例子 + ? tooltip
 * 默认折叠,点击展开;移动端友好(无 hover 依赖)
 */
export function BeginnersGuide({
  signal,
  volumeRatio,
  position,
}: {
  signal: SignalFusion | undefined;
  volumeRatio: number | null;
  position: PositionIndicator | undefined;
}) {
  const [open, setOpen] = useState(true);
  // 基于实际数据生成每个步骤的"当前例子"
  const direction =
    signal?.view === 'bullish'
      ? '看多'
      : signal?.view === 'bearish'
        ? '看空'
        : signal
          ? '中性'
          : '点击「开始分析」后给出';
  const volLabel =
    volumeRatio == null
      ? '先分析后才会有'
      : volumeRatio >= 1.5
        ? `放量 ${volumeRatio.toFixed(2)} —— 资金在加码`
        : volumeRatio <= 0.7
          ? `缩量 ${volumeRatio.toFixed(2)} —— 资金在退潮`
          : `量能平稳 ${volumeRatio.toFixed(2)}`;
  const bandLabel =
    position?.riskBand === 'high'
      ? '当前处于高位区间,慎追'
      : position?.riskBand === 'low'
        ? '当前处于低位区间,慎接飞刀'
        : position?.riskBand
          ? '当前处于中位区间,空间大'
          : '先分析后才会有';
  const signalLabel = signal ? `${signal.viewLabel} · ${signal.score}分` : '先分析后才会有';

  const steps = [
    {
      title: '1. 方向',
      hint: '股票当下是涨势、跌势,还是震荡?这是"看多/看空/中性"的第一判断。',
      example: `机械信号:${direction}`,
    },
    {
      title: '2. 量能',
      hint: '成交量是否在放大?放量上涨更可信,缩量上涨容易回调;放量下跌要警惕。',
      example: volLabel,
    },
    {
      title: '3. 价位',
      hint: '当前价相对近 120 日是高位、中位还是低位?同样一支票,60 块和 30 块买意义不同。',
      example: bandLabel,
    },
    {
      title: '4. 支撑/压力',
      hint: '下面有支撑就跌不深,上面有压力就涨不动;关键位置决定买卖点。',
      example:
        position?.supportPrice != null
          ? `参考支撑 ¥${position.supportPrice.toFixed(2)}`
          : '先分析后才会有',
    },
    {
      title: '5. 信号确认',
      hint: '机械信号 + 历史胜率 + AI 白话解读,三者一致时才值得动手。',
      example: signalLabel,
    },
  ];

  return (
    <GlassCard padding="sm" className="space-y-2 border border-accent/25 bg-accent-subtle/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 text-left"
        aria-expanded={open}
      >
        <span className="text-xs font-semibold text-text-pri inline-flex items-center gap-1.5">
          📖 新手速看 · 5 步读懂一只股
          <span className="text-[10px] font-normal text-text-ter">(点击收起)</span>
        </span>
        <span
          className={clsx(
            'text-text-ter text-xs transition-transform',
            open ? 'rotate-180' : '',
          )}
          aria-hidden
        >
          ▾
        </span>
      </button>
      {open && (
        <ol className="space-y-2 text-xs">
          {steps.map((s) => (
            <li key={s.title} className="flex flex-col gap-1">
              <div className="flex items-start gap-2">
                <span className="font-semibold text-accent shrink-0">{s.title}</span>
                <span className="text-text-sec leading-relaxed flex-1">{s.hint}</span>
              </div>
              <div className="ml-0 pl-0 rounded-lg bg-bg-subtle/60 border border-border-def/40 px-2.5 py-1.5">
                <span className="text-[10px] text-text-ter mr-1.5">当前:</span>
                <span className="font-mono text-text-pri">{s.example}</span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </GlassCard>
  );
}

function Mini({ label, value, suffix }: { label: string; value: number | null; suffix?: string }) {
  return (
    <div className="rounded-lg bg-bg-subtle px-2 py-1.5">
      <div className="text-[10px] text-text-ter uppercase">{label}</div>
      <div className="text-sm font-mono text-text-pri">
        {value != null ? `${value.toFixed(label === 'HIST' || label === 'MACD' || label.includes('DIF') || label.includes('DEA') ? 4 : 2)}${suffix ?? ''}` : '--'}
      </div>
    </div>
  );
}

// === v2.5 操作参考结构化区块(rationale + 6 字段网格 + 可选 T 区块) ===

type RoleColor = {
  cardCls: string;
  labelCls: string;
};

const ROLE_COLOR: Record<'empty' | 'profit' | 'loss', RoleColor> = {
  empty: {
    cardCls: 'rounded bg-accent-subtle/60 border border-accent/20 p-3',
    labelCls: 'text-xs text-accent font-semibold',
  },
  profit: {
    cardCls: 'rounded bg-success-bg border border-success/30 p-3',
    labelCls: 'text-xs text-success font-semibold',
  },
  loss: {
    cardCls: 'rounded bg-danger-bg border border-danger/30 p-3',
    labelCls: 'text-xs text-danger font-semibold',
  },
};

const T_CARD_UNSUITABLE_CLS =
  'rounded-xl bg-warn-bg/30 border border-warn/20 p-3';

function OperationAdviceBlock({ analysis }: { analysis: AnalysisResult }) {
  const ai = analysis.ai;
  if (!ai) return null;
  // 兜底:旧缓存/异常数据可能缺 positionStatus 或不是枚举值 → fallback 'empty'
  const ps: 'empty' | 'profit' | 'loss' =
    ai.positionStatus === 'profit' || ai.positionStatus === 'loss' ? ai.positionStatus : 'empty';
  const palette = ROLE_COLOR[ps];
  const pctTxt =
    analysis.costBasisPct != null && ps !== 'empty'
      ? `${analysis.costBasisPct > 0 ? '+' : ''}${((analysis.costBasisPct as number) * 100).toFixed(2)}%`
      : null;
  const a = ai.advice || {
    rationale: '',
    price: { entryOrExitRange: '', stopLoss: '' },
    positionPct: '',
    trigger: '',
    holdingWindow: '',
    notAction: '',
    tStrategy: null,
  };
  const cells: Array<{ icon: string; label: string; value: string }> = [
    { icon: '💰', label: '价位', value: a.price?.entryOrExitRange ?? '' },
    { icon: '🛑', label: '止损', value: a.price?.stopLoss ?? '' },
    { icon: '📊', label: '仓位', value: a.positionPct ?? '' },
    { icon: '⚡', label: '触发', value: a.trigger ?? '' },
    { icon: '⏰', label: '时间', value: a.holdingWindow ?? '' },
    { icon: '🚫', label: '不动', value: a.notAction ?? '' },
  ];
  const visibleCells = cells.filter((c) => c.value);
  const t = a.tStrategy;
  const showT = (ps === 'profit' || ps === 'loss') && t != null;
  return (
    <div className="space-y-2">
      {/* 头部:rationale(整行)+ 角色 + 浮盈/浮亏 */}
      <div className={palette.cardCls}>
        <div className="flex items-baseline justify-between mb-2">
          <div className={palette.labelCls}>{ai.adviceRole || '操作参考'}</div>
          {pctTxt && <div className={palette.labelCls}>{pctTxt}</div>}
        </div>
        {a.rationale && (
          <p className="text-sm text-text-pri leading-relaxed whitespace-pre-wrap">
            {a.rationale}
          </p>
        )}
      </div>
      {/* 6 字段网格 */}
      {visibleCells.length > 0 && (
        <div className="grid grid-cols-1 ">
          {visibleCells.map((c) => (
            <div key={c.label} className={palette.cardCls}>
              <div className={palette.labelCls}>
                {c.icon} {c.label}
              </div>
              <p className="text-sm text-text-pri leading-relaxed whitespace-pre-wrap">
                {c.value}
              </p>
            </div>
          ))}
        </div>
      )}
      {/* 做 T 区块(仅 profit/loss 渲染) */}
      {showT && t && (
        <div
          className={
            t.suitable
              ? 'rounded-xl bg-accent-subtle/60 border border-accent/20 p-3'
              : T_CARD_UNSUITABLE_CLS
          }
        >
          <div className="flex items-baseline justify-between mb-2">
            <div className={palette.labelCls}>🔄 做 T 参考</div>
            <div className={palette.labelCls}>
              {t.suitable ? '适合 ✓' : '不适合'}
            </div>
          </div>
          {t.suitable ? (
            <div className="grid grid-cols-1  gap-2">
              {[
                { icon: '📏', label: 'T 区间', value: t.tRange },
                { icon: '🛡️', label: '底仓', value: t.basePositionPct },
                { icon: '📤', label: '卖出触发', value: t.sellTrigger },
                { icon: '📥', label: '买回触发', value: t.buybackTrigger },
                { icon: '🛑', label: '底仓止损', value: t.stopLoss },
                { icon: '🚫', label: '不做 T', value: t.unsuitableSignals },
              ]
                .filter((c) => c.value)
                .map((c) => (
                  <div key={c.label} className={palette.cardCls}>
                    <div className={palette.labelCls}>
                      {c.icon} {c.label}
                    </div>
                    <p className="text-sm text-text-pri leading-relaxed whitespace-pre-wrap">
                      {c.value}
                    </p>
                  </div>
                ))}
            </div>
          ) : (
            <p className="text-sm text-text-sec leading-relaxed whitespace-pre-wrap">
              {t.unsuitableSignals || '当前行情不适合做 T'}
            </p>
          )}
        </div>
      )}
    </div>
  );
}