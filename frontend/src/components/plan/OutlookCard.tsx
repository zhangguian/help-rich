'use client';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import type { BattlePlanOutlook } from '@/lib/planTypes';

const STANCE_STYLE: Record<string, string> = {
  bullish: 'text-up',
  bearish: 'text-down',
  neutral: 'text-text-pri',
  unknown: 'text-text-ter',
};

const DIM_STYLE: Record<string, string> = {
  bull: 'text-up',
  bear: 'text-down',
  flat: 'text-text-sec',
  missing: 'text-text-ter',
};

export function OutlookCard({ outlook }: { outlook: BattlePlanOutlook }) {
  return (
    <Card padding="sm" data-testid="outlook-card">
      {/* 结论前置:先给倾向,再给维度依据 */}
      <div className="flex items-baseline gap-2">
        <span className={clsx('text-[15px] font-bold', STANCE_STYLE[outlook.stance] ?? '')}>
          {outlook.stanceLabel}
        </span>
        <span className="ml-auto font-mono text-[10px] text-text-ter">
          {outlook.dimsEffective}/{outlook.dimsTotal} 维度
        </span>
      </div>

      <p className="mt-1 text-[10px] leading-[1.45] text-text-ter">{outlook.disclaimer}</p>

      <ul className="mt-2">
        {outlook.dims.map((d) => (
          <li key={d.key} className="py-1.5 border-b border-dashed border-border-def last:border-b-0">
            <div className="flex items-baseline gap-2">
              <span className="text-[11px] text-text-sec">{d.label}</span>
              <span className={clsx('ml-auto font-mono text-[10.5px]', DIM_STYLE[d.state] ?? '')}>
                {d.state === 'missing' ? '缺失' : d.score > 0 ? '偏多' : d.score < 0 ? '偏空' : '中性'}
              </span>
            </div>
            <div className="mt-0.5 text-[10.5px] leading-[1.45] text-text-ter">{d.detail}</div>
          </li>
        ))}
      </ul>

      {/* 关键位:2×2 一眼扫到压力 / 支撑 / 均线 */}
      <div className="mt-2 pt-1.5 border-t border-border-def">
        <div className="text-[10px] text-text-ter">关键位</div>
        <div className="mt-1 grid grid-cols-2 gap-1">
          <Level k="压力位" v={outlook.keyLevels.resistance[0]} tone="text-down" />
          <Level k="支撑位" v={outlook.keyLevels.support[0]} tone="text-up" />
          <Level k="MA5" v={outlook.keyLevels.ma5} />
          <Level k="MA20" v={outlook.keyLevels.ma20} />
        </div>
        {outlook.keyLevels.close !== null && (
          <div className="mt-1.5 font-mono text-[10px] text-text-ter">
            上证收盘 {outlook.keyLevels.close}
            {outlook.keyLevels.ma10 !== null && ` · MA10 ${outlook.keyLevels.ma10}`}
          </div>
        )}
      </div>
    </Card>
  );
}

/** 关键位的一格 */
function Level({
  k,
  v,
  tone,
}: {
  k: string;
  v: number | null | undefined;
  tone?: string;
}) {
  return (
    <div className="rounded bg-bg-subtle px-1.5 py-1">
      <div className="text-[9.5px] text-text-ter">{k}</div>
      <div className={clsx('mt-px font-mono text-[11px] tabular-nums', tone ?? 'text-text-pri')}>
        {v != null ? v.toFixed(2) : '—'}
      </div>
    </div>
  );
}
