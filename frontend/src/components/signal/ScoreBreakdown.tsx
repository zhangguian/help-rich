'use client';

import clsx from 'clsx';

/**
 * 评分维度条(P4.5 辅助)
 *
 * 5 维度(集中度/价格合理性/操作间隔/市场环境/板块热度)各 20 分
 */
export function ScoreBreakdown({
  breakdown,
  className,
}: {
  breakdown: Record<string, number> | null;
  className?: string;
}) {
  if (!breakdown) return null;
  const entries = Object.entries(breakdown);

  return (
    <div className={clsx('space-y-2', className)}>
      {entries.map(([k, v]) => {
        const pct = Math.max(0, Math.min(100, (v / 20) * 100));
        const color =
          pct >= 75
            ? 'bg-down'
            : pct >= 50
              ? 'bg-warn'
              : 'bg-up';
        return (
          <div key={k}>
            <div className="flex justify-between text-xs text-text-sec mb-1">
              <span>{k}</span>
              <span className="font-mono tabular-nums">{v} 分</span>
            </div>
            <div className="h-2 rounded-sm bg-bg-subtle overflow-hidden">
              <div
                className={clsx('h-full transition-all duration-500', color)}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}