'use client';

import { AnimatePresence, motion } from 'framer-motion';
import clsx from 'clsx';

import { GlassCard } from '@/components/ui/GlassCard';
import { Button } from '@/components/ui/Button';
import { TermHint } from '@/components/ui/TermHint';
import type {
  AnalysisResult,
  SignalFusion,
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
  neutral: { label: '中性', cls: 'text-text-sec border-white/20 bg-white/5' },
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
  neutral: { label: '中性', cls: 'text-text-sec border-white/20 bg-white/5' },
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
  onRefresh,
}: {
  analysis: AnalysisResult | null;
  started: boolean;
  loading: boolean;
  onRefresh: () => void;
}) {
  const ind = analysis?.indicators;

  return (
    <div className="space-y-3 overflow-y-auto min-h-0">
      {/* 顶部置顶:机械信号卡(确定性引擎,与 AI 卡并存) */}
      {ind && (
        <SignalPanel
          signal={ind.signal}
          volumePrice={ind.volumePrice}
          liar={ind.liar}
          position={ind.position}
          patterns={ind.patterns}
        />
      )}

      {/* AI 分析卡(LLM 白话解读) */}
      <GlassCard padding="md" className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs text-text-ter uppercase tracking-wide">AI 分析</span>
          <Button variant="ghost" onClick={onRefresh} disabled={loading}>
            {loading
              ? '分析中…'
              : started
                ? '🔄 重新分析'
                : '✨ 开始分析'}
          </Button>
        </div>

        <AnimatePresence mode="wait">
          {loading ? (
            <motion.div key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="h-4 w-24 rounded bg-white/10 animate-pulse" />
              <div className="h-3 w-full rounded bg-white/5 animate-pulse mt-3" />
              <div className="h-3 w-5/6 rounded bg-white/5 animate-pulse mt-2" />
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
              <div className="flex items-center gap-2">
                <span
                  className={clsx(
                    'px-3 py-1 rounded-full text-sm font-semibold border',
                    VIEW_META[analysis.ai.view].cls,
                  )}
                >
                  {VIEW_META[analysis.ai.view].label}
                </span>
                <span className="text-sm text-text-sec">{analysis.ai.viewReason}</span>
              </div>
              <p className="text-sm text-text-sec leading-relaxed">{analysis.ai.trend}</p>
              <p className="text-sm text-text-sec leading-relaxed">{analysis.ai.volumeNote}</p>
              {analysis.ai.keyLevels.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {analysis.ai.keyLevels.map((lvl, i) => (
                    <span
                      key={i}
                      className="text-xs px-2 py-1 rounded-lg bg-white/5 border border-white/10 text-text-sec font-mono"
                      title={lvl.note}
                    >
                      {lvl.type === 'support' ? '支撑' : lvl.type === 'pressure' ? '压力' : '企稳'}{' '}
                      {lvl.price}
                    </span>
                  ))}
                </div>
              )}
              <div className="rounded-xl bg-accent-subtle/60 border border-accent/20 p-3">
                <div className="text-xs text-accent font-semibold mb-1">操作参考</div>
                <p className="text-sm text-text-pri leading-relaxed">{analysis.ai.advice}</p>
              </div>
              <p className="text-xs text-text-ter leading-relaxed">
                ⚠ {analysis.ai.riskWarning}
              </p>
            </motion.div>
          ) : started ? (
            <motion.p
              key="noai"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-sm text-text-ter"
            >
              AI 暂不可用(未配置 Key 或服务异常),以下为纯技术指标。
            </motion.p>
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
        <span className="text-xs text-text-ter uppercase tracking-wide">技术指标</span>
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
                  <div key={k} className="rounded-lg bg-white/5 px-2 py-1.5">
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
            <div className="rounded-xl bg-white/5 p-3 space-y-2">
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

function SignalPanel({
  signal,
  volumePrice,
  liar,
  position,
  patterns,
}: {
  signal: SignalFusion | undefined;
  volumePrice: VolumePriceIndicator;
  liar: LiarIndicator;
  position: PositionIndicator;
  patterns: PatternMatch[];
}) {
  // 旧缓存(24h IndexedDB)可能不含 signal 字段,降级显示而不崩溃
  if (!signal) {
    return (
      <GlassCard padding="md" className="space-y-3 border border-accent/20">
        <span className="text-xs text-text-ter uppercase tracking-wide">机械信号 · 确定性引擎</span>
        <p className="text-sm text-text-ter">
          旧缓存数据(不含机械信号),点击下方「✨ 开始分析」刷新即可看到
        </p>
      </GlassCard>
    );
  }
  const view = SIGNAL_VIEW_META[signal.view];
  const conf = CONFIDENCE_META[signal.confidence];

  return (
    <GlassCard padding="md" className="space-y-3 border border-accent/20">
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-ter uppercase tracking-wide">机械信号 · 确定性引擎</span>
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
      <div className="flex flex-wrap gap-1.5 pt-1 border-t border-white/10">
        {volumePrice.label && (
          <span
            className={clsx(
              'text-xs px-2 py-0.5 rounded-full border',
              volumePrice.direction === 'healthy_up'
                ? 'text-up border-up/30'
                : volumePrice.direction === 'liar_up_suspect' || volumePrice.direction === 'panic_sell'
                  ? 'text-down border-down/30'
                  : 'text-text-sec border-white/20',
            )}
          >
            {volumePrice.emoji} {volumePrice.label}
          </span>
        )}
        {liar.bullLiars.length > 0 && (
          <span className="text-xs px-2 py-0.5 rounded-full border border-yellow-400/40 text-yellow-300">
            ⚠️ 诱多 {liar.bullLiars.length} 类
          </span>
        )}
        {liar.bearLiars.length > 0 && (
          <span className="text-xs px-2 py-0.5 rounded-full border border-blue-400/40 text-blue-300">
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
                  : 'text-text-sec border-white/20',
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
      ? { label: '触上轨', cls: 'text-yellow-300' }
      : boll.position === 'touching_lower'
        ? { label: '触下轨', cls: 'text-blue-300' }
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
                  : 'text-text-sec border-white/20',
            )}
          >
            {p.emoji} {p.name}
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
            <div className="font-semibold text-yellow-300 mb-0.5">⚠️ {p.name}</div>
            <div className="text-text-sec font-mono">{p.note}</div>
          </div>
        ))}
        {liar.bearLiars.map((p, i) => (
          <div
            key={`B${i}`}
            className="rounded-lg bg-blue-500/10 border border-blue-500/20 p-2 text-xs"
          >
            <div className="font-semibold text-blue-300 mb-0.5">🪤 {p.name}</div>
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
    </div>
  );
}

function Mini({ label, value, suffix }: { label: string; value: number | null; suffix?: string }) {
  return (
    <div className="rounded-lg bg-white/5 px-2 py-1.5">
      <div className="text-[10px] text-text-ter uppercase">{label}</div>
      <div className="text-sm font-mono text-text-pri">
        {value != null ? `${value.toFixed(label === 'HIST' || label === 'MACD' || label.includes('DIF') || label.includes('DEA') ? 4 : 2)}${suffix ?? ''}` : '--'}
      </div>
    </div>
  );
}