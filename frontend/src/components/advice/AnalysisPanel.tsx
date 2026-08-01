'use client';

import { AnimatePresence, motion } from 'framer-motion';
import clsx from 'clsx';

import { GlassCard } from '@/components/ui/GlassCard';
import { Button } from '@/components/ui/Button';

export interface AnalysisResult {
  stockCode: string;
  indicators: {
    latestClose: number;
    ma: { ma5: number | null; ma10: number | null; ma20: number | null; ma60: number | null };
    volume: { ratio: number | null; state: 'expand' | 'shrink' | 'normal' | null };
    channel: { state: 'up' | 'down' | 'sideways'; slope: number | null; upper: number | null; lower: number | null };
    supportPressure: { support: number[]; pressure: number[] };
    stabilize: {
      state: boolean;
      price: number | null;
      reasons: { name: string; ok: boolean; note: string }[];
    };
  };
  ai: {
    view: 'bullish' | 'bearish' | 'neutral';
    viewReason: string;
    trend: string;
    volumeNote: string;
    keyLevels: { type: string; price: number; note: string }[];
    advice: string;
    riskWarning: string;
  } | null;
}

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

/**
 * 右侧上栏 · 操作提示(roadmap 功能3/4)
 *
 * AI 分析卡(看多/看空/中性大徽章)+ 5 张技术指标卡 + 关键价位 chips。
 * AI 不可用 → 提示条 + 纯指标展示(降级)。
 */
export function AnalysisPanel({
  analysis,
  loading,
  onRefresh,
}: {
  analysis: AnalysisResult | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  const ind = analysis?.indicators;

  return (
    <div className="space-y-3 overflow-y-auto min-h-0">
      {/* AI 分析卡 */}
      <GlassCard padding="md" className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs text-text-ter uppercase tracking-wide">AI 分析</span>
          <Button variant="ghost" onClick={onRefresh} disabled={loading}>
            {loading ? '分析中…' : '🔄 重新分析'}
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
          ) : (
            <motion.p
              key="noai"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-sm text-text-ter"
            >
              AI 暂不可用(未配置 Key 或服务异常),以下为纯技术指标。
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
                <span className="text-text-sec">通道</span>
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
                <span className="text-text-sec">量能</span>
                <span className={clsx('font-semibold', VOLUME_META[ind.volume.state ?? 'normal']?.cls ?? 'text-text-sec')}>
                  {ind.volume.ratio != null
                    ? `${VOLUME_META[ind.volume.state ?? 'normal']?.label ?? '量能正常'} ${ind.volume.ratio.toFixed(2)}`
                    : '数据不足'}
                </span>
              </div>
              <p className="text-xs text-text-ter mt-1">近5日均量 ÷ 前20日均量(≥1.5 放量,≤0.7 缩量)</p>
            </div>

            {/* 均线 */}
            <div>
              <div className="text-sm text-text-sec mb-1.5">均线</div>
              <div className="grid grid-cols-2 gap-1.5">
                {(['ma5', 'ma10', 'ma20', 'ma60'] as const).map((k) => (
                  <div key={k} className="rounded-lg bg-white/5 px-2 py-1.5">
                    <div className="text-[10px] text-text-ter uppercase">{k}</div>
                    <div className="text-sm font-mono text-text-pri">{ind.ma[k] ?? '--'}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* 支撑 / 压力 */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <div className="text-xs text-text-ter mb-1">支撑位</div>
                <div className="flex flex-wrap gap-1">
                  {ind.supportPressure.support.length === 0 && (
                    <span className="text-xs text-text-ter">暂无</span>
                  )}
                  {ind.supportPressure.support.map((p) => (
                    <span key={p} className="text-xs font-mono px-1.5 py-0.5 rounded bg-down-bg text-down">
                      {p}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-xs text-text-ter mb-1">压力位</div>
                <div className="flex flex-wrap gap-1">
                  {ind.supportPressure.pressure.length === 0 && (
                    <span className="text-xs text-text-ter">暂无</span>
                  )}
                  {ind.supportPressure.pressure.map((p) => (
                    <span key={p} className="text-xs font-mono px-1.5 py-0.5 rounded bg-up-bg text-up">
                      {p}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* 企稳 */}
            <div className="rounded-xl bg-white/5 p-3 space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-text-sec">企稳点</span>
                <span className={clsx('font-semibold', ind.stabilize.state ? 'text-accent' : 'text-text-ter')}>
                  {ind.stabilize.state ? '已企稳 ✓' : '未企稳'}
                  {ind.stabilize.price != null && (
                    <span className="font-mono text-text-pri"> @ {ind.stabilize.price}</span>
                  )}
                </span>
              </div>
              {ind.stabilize.reasons.map((r) => (
                <div key={r.name} className="flex items-center gap-2 text-xs">
                  <span className={r.ok ? 'text-accent' : 'text-text-ter'}>{r.ok ? '✓' : '✗'}</span>
                  <span className="text-text-sec">{r.name}</span>
                  <span className="text-text-ter font-mono truncate">{r.note}</span>
                </div>
              ))}
              <p className="text-xs text-text-ter">站住企稳点不破,可视为多头占优;跌破则谨慎</p>
            </div>
          </div>
        )}
      </GlassCard>
    </div>
  );
}
