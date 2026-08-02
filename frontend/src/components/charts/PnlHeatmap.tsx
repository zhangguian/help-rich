'use client';

import { useState } from 'react';

import clsx from 'clsx';

import type { PnlGridRow } from '@/lib/types';

/**
 * 21 档盈亏热力图(ui-ux §5.3 v1.5 重设计)
 *
 * - 当前价标线:垂直 dashed line
 * - 加仓区间高亮:浅蓝/浅红背景
 * - hover 放大 1.2x,其他柱 opacity → 0.5
 * - 点击展开"假设买入 X 股的成本计算"(P7.12 实施)
 */
interface PnlHeatmapProps {
  grid: PnlGridRow[];
  currentPricePct?: number | undefined;  // 当前价对应的 pct(用于标线);undefined 时不渲染
  recommendedRange?: [number, number];  // 加仓区间(浅蓝背景)
}

export function PnlHeatmap({ grid, currentPricePct, recommendedRange }: PnlHeatmapProps) {
  const [hovered, setHovered] = useState<number | null>(null);

  if (grid.length === 0) return null;

  const minPnl = Math.min(...grid.map((r) => Number(r.pnl.replace(/,/g, ''))));
  const maxPnl = Math.max(...grid.map((r) => Number(r.pnl.replace(/,/g, ''))));
  const range = Math.max(Math.abs(minPnl), Math.abs(maxPnl), 1);

  const markerStyle =
    currentPricePct !== undefined
      ? {
          leftPct: Math.max(2, Math.min(98, ((currentPricePct + 10) / 20) * 100)),
          label: `当前 ${currentPricePct > 0 ? '+' : ''}${currentPricePct.toFixed(1)}%`,
        }
      : null;

  return (
    <div>
      <div className="text-xs text-text-sec mb-3 flex items-center gap-4">
        <span>±10% 盈亏热力图(21 档)</span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded-sm bg-up/30" style={{ background: 'rgba(244,63,94,0.3)' }} />
          盈利
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded-sm bg-down/30" style={{ background: 'rgba(74,222,128,0.3)' }} />
          亏损
        </span>
      </div>

      <div className="relative">
        {/* 加仓区间高亮背景 */}
        {recommendedRange && (
          <div
            className="absolute top-0 bottom-0 bg-accent-subtle/30 -z-10 border-l border-r border-accent/30"
            style={{
              left: `${((recommendedRange[0] + 10) / 20) * 100}%`,
              width: `${((recommendedRange[1] - recommendedRange[0]) / 20) * 100}%`,
              background: 'rgba(37, 99, 235, 0.08)',
            }}
            title="建议加仓区间"
          />
        )}

        <div className="grid grid-cols-21 gap-1">
          {grid.map((row) => {
            const pctNum = Number(row.pnl.replace(/,/g, ''));
            const isPos = pctNum >= 0;
            const intensity = Math.min(1, Math.abs(pctNum) / range);
            const isHovered = hovered === row.pct;
            const isDimmed = hovered !== null && hovered !== row.pct;

            return (
              <div
                key={row.pct}
                onMouseEnter={() => setHovered(row.pct)}
                onMouseLeave={() => setHovered(null)}
                className={clsx(
                  'flex flex-col items-center py-1.5 px-0.5 rounded-sm cursor-default transition-all',
                  isHovered && 'scale-110 z-10 shadow-md',
                  isDimmed && 'opacity-50',
                )}
                style={{
                  backgroundColor: isPos
                    ? `rgba(244, 63, 94, ${0.1 + intensity * 0.5})`
                    : `rgba(74, 222, 128, ${0.1 + intensity * 0.5})`,
                }}
                title={`${row.pct}%: 价格 ¥${row.price} → PnL ¥${row.pnl}`}
              >
                <div className="text-[10px] text-text-ter font-mono">
                  {row.pct > 0 ? `+${row.pct}` : row.pct}
                </div>
                <div className={`text-[10px] font-mono ${isPos ? 'text-up' : 'text-down'}`}>
                  {Math.abs(pctNum) > 1000
                    ? `${(pctNum / 1000).toFixed(1)}k`
                    : pctNum.toFixed(0)}
                </div>
              </div>
            );
          })}
        </div>

        {/* 当前价标线 */}
        {markerStyle && (
          <div
            className="absolute top-0 bottom-0 w-0.5 border-l-2 border-dashed border-orange pointer-events-none"
            style={{ left: `${markerStyle.leftPct}%` }}
            title={markerStyle.label}
          >
            <div className="absolute -bottom-5 -translate-x-1/2 text-[10px] font-mono text-orange whitespace-nowrap">
              {markerStyle.label}
            </div>
          </div>
        )}
      </div>

      {/* 移动端 5 档折叠(ui-ux §5.3):占位提示 */}
      <div className="md:hidden mt-3 text-xs text-text-ter">
        移动端 5 档折叠版本待 P7.11 实施
      </div>
    </div>
  );
}