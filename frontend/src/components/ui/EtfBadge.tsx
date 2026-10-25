'use client';

import clsx from 'clsx';

import { instrumentBadgeTitle, resolveInstrument } from '@/lib/instrument';

/**
 * 场内 ETF 品种徽章
 *
 * **配色语义**:amber(warn 家族)表示「这是另一类标的」。
 * 刻意避开 accent(青 = 选中/焦点)与 danger(红 = 判定结论)——
 * 徽章是**品种分类**,不是判定结论,不能借用那两支色。
 *
 * 三种形态:
 * - 表内 ETF        → 实线 amber 徽章
 * - 表内 T+0 品种   → 徽章里再加一个深底 `T+0` 小标
 * - 表外 ETF        → 虚线灰徽章(「未收录,按保守口径算」)
 * - 股票            → 不渲染
 */
export function EtfBadge({
  code,
  className,
  showT0 = true,
}: {
  code: string;
  className?: string;
  showT0?: boolean;
}) {
  const meta = resolveInstrument(code);
  if (!meta.isEtf) return null;

  const title = instrumentBadgeTitle(meta);

  if (!meta.known) {
    return (
      <span
        className={clsx(
          'inline-flex items-center gap-1 text-[10px] px-1.5 py-px rounded-full border border-dashed border-border-def text-text-ter shrink-0 align-middle',
          className,
        )}
        title={title}
      >
        📊 ETF
      </span>
    );
  }

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-px rounded-full border border-warn/30 bg-warn-bg text-warn shrink-0 align-middle',
        className,
      )}
      title={title}
    >
      📊 ETF
      {showT0 && meta.t0 && (
        <span className="text-[9px] font-bold tracking-wide px-1 rounded-sm bg-warn/30 text-warn">
          T+0
        </span>
      )}
    </span>
  );
}
