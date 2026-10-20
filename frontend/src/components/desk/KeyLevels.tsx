'use client';

import clsx from 'clsx';

import type { AnalysisResult } from '@/lib/types';

/**
 * 关键价位(v0.8 中栏底部)
 *
 * 盯盘时真正要回答的问题是「**这里能不能买 / 该不该卖**」,
 * 而不是「指标是涨还是跌」。所以把支撑 / 企稳 / 压力三条价位提到图表正下方,
 * 让人一眼看完「K 线 + 该在哪个价位动手」。
 *
 * **数据来源优先级**:
 * 1. AI 解读里的 `key_levels`(LLM 给的白话价位,含理由)—— 首选,因为带解释
 * 2. 机械指标 `supportPressure` / `stabilize` / `position` —— AI 还没跑时兜底
 *
 * 两者都没有时显示引导文案,不做任何假数据。
 */

type LevelKind = 'support' | 'stabilize' | 'pressure';

interface LevelItem {
  kind: LevelKind;
  price: number;
  note: string;
}

const KIND_META: Record<LevelKind, { label: string; cls: string }> = {
  support: { label: '支撑', cls: 'border-l-down' },
  stabilize: { label: '企稳', cls: 'border-l-warn' },
  pressure: { label: '压力', cls: 'border-l-up' },
};

const KIND_ORDER: Record<string, LevelKind> = {
  support: 'support',
  支撑: 'support',
  stabilize: 'stabilize',
  企稳: 'stabilize',
  pressure: 'pressure',
  压力: 'pressure',
};

function fmtPrice(p: number): string {
  return p.toFixed(2);
}

/** 从分析结果里抽价位,先 AI 后机械,按价格升序、去掉重复价位 */
export function buildKeyLevels(analysis: AnalysisResult | null): LevelItem[] {
  const out: LevelItem[] = [];
  const seen = new Set<string>();

  const push = (kind: LevelKind, price: number | null | undefined, note: string) => {
    if (price == null || !Number.isFinite(price) || price <= 0) return;
    const key = price.toFixed(2);
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ kind, price, note });
  };

  // 1) AI 解读的 key_levels(带白话理由)
  const aiLevels = analysis?.ai?.keyLevels ?? [];
  for (const lv of aiLevels) {
    const kind = KIND_ORDER[String(lv.type ?? '').toLowerCase()] ?? 'support';
    push(kind, Number(lv.price), lv.note ?? '');
  }

  const ind = analysis?.indicators;

  // 2) 机械指标兜底
  if (ind) {
    const sp = ind.supportPressure;
    const support = sp?.support ?? [];
    const pressure = sp?.pressure ?? [];
    // 机械支撑取最近的一个,压力取最近的两个
    if (support.length > 0) {
      push('support', support[support.length - 1], '近端支撑,跌破看下一档');
    }
    if (pressure.length > 0) {
      push('pressure', pressure[pressure.length - 1], '上方压力,需放量突破');
    }
    if (pressure.length > 1) {
      push('pressure', pressure[pressure.length - 2], '更上方压力位');
    }
    const st = ind.stabilize?.price;
    if (st != null && ind.stabilize?.state) {
      push('stabilize', st, '企稳信号位,站上可观察反弹');
    }
    const pos = ind.position;
    if (pos?.supportPrice != null) {
      push('support', pos.supportPrice, '参考支撑(近 20 日低点下方 2%)');
    }
    if (pos?.p20 != null && pos?.p80 != null) {
      push('support', pos.p20, '近 120 日 P20 分位,历史低位区');
      push('pressure', pos.p80, '近 120 日 P80 分位,历史高位区');
    }
  }

  out.sort((a, b) => a.price - b.price);
  return out.slice(0, 4);
}

export function KeyLevels({ analysis }: { analysis: AnalysisResult | null }) {
  const levels = buildKeyLevels(analysis);

  return (
    <section className="shrink-0 bg-bg-surface border-t border-border-def px-3 py-2">
      <div className="flex items-baseline gap-2 mb-1.5">
        <span className="text-[11px] font-semibold text-text-pri">关键价位</span>
        <span className="text-[10px] text-text-ter">
          {levels.length > 0 ? '来自技术指标与 AI 解读 · 位置参考' : '分析后显示支撑 / 企稳 / 压力'}
        </span>
      </div>
      {levels.length > 0 ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5">
          {levels.map((lv, i) => (
            <div
              key={`${lv.kind}-${lv.price}-${i}`}
              className={clsx(
                'bg-bg-elevated border border-border-def border-l-2 rounded-md px-2 py-1.5 flex flex-col gap-0.5 min-w-0',
                KIND_META[lv.kind].cls,
              )}
            >
              <span className="text-[9.5px] text-text-ter font-mono tracking-wider">
                {KIND_META[lv.kind].label}
              </span>
              <span className="text-[14px] font-mono font-semibold tabular-nums text-text-pri leading-tight">
                {fmtPrice(lv.price)}
              </span>
              {lv.note && (
                <span className="text-[10px] text-text-ter leading-snug line-clamp-2">
                  {lv.note}
                </span>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="h-[52px] rounded-md bg-bg-elevated border border-border-def animate-pulse" />
      )}
    </section>
  );
}
