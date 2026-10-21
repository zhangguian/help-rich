'use client';

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
    <Card>
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">明日市场预期</h3>
        <span className={`text-lg font-bold ${STANCE_STYLE[outlook.stance] ?? ''}`}>
          倾向：{outlook.stanceLabel}
        </span>
      </div>

      <p className="mt-1 text-[11px] text-text-ter">{outlook.disclaimer}</p>

      <ul className="mt-3 space-y-2">
        {outlook.dims.map((d) => (
          <li key={d.key} className="flex items-start gap-2 text-xs">
            <span className="w-16 shrink-0 text-text-sec">{d.label}</span>
            <span className={`w-10 shrink-0 font-mono ${DIM_STYLE[d.state] ?? ''}`}>
              {d.state === 'missing' ? '缺失' : d.score > 0 ? '偏多' : d.score < 0 ? '偏空' : '中性'}
            </span>
            <span className="flex-1 text-text-pri">{d.detail}</span>
          </li>
        ))}
      </ul>

      <div className="mt-4 border-t border-border-def pt-3 text-xs">
        <div className="text-text-sec">关键位</div>
        <div className="mt-1.5 grid grid-cols-2 gap-2">
          <div>
            <div className="text-[11px] text-text-ter">支撑</div>
            <div className="font-mono text-up">
              {outlook.keyLevels.support.length
                ? outlook.keyLevels.support.join(' / ')
                : '—'}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-text-ter">压力</div>
            <div className="font-mono text-down">
              {outlook.keyLevels.resistance.length
                ? outlook.keyLevels.resistance.join(' / ')
                : '—'}
            </div>
          </div>
        </div>
        {outlook.keyLevels.close !== null && (
          <div className="mt-2 text-[11px] text-text-ter">
            上证收盘 {outlook.keyLevels.close} · MA5 {outlook.keyLevels.ma5 ?? '—'} · MA10{' '}
            {outlook.keyLevels.ma10 ?? '—'} · MA20 {outlook.keyLevels.ma20 ?? '—'}
          </div>
        )}
      </div>
    </Card>
  );
}
