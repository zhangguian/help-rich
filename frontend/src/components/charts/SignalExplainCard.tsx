'use client';

import clsx from 'clsx';
import type { CSSProperties } from 'react';

import type { GlossaryEntry, SignalTermKind } from '@/lib/glossary';

/**
 * 信号解释浮层(K 线图 marker 悬停)
 *
 * 为什么是 DOM 而不是 canvas:
 * lightweight-charts 的 marker 画在 canvas 上,没有 DOM 节点,
 * 既挂不上 title / hover,也没法做可访问的说明。所以浮层单独用 DOM 渲染,
 * 叠在图表容器上。
 *
 * 内容四段(与视觉稿一致):
 * 这是什么 / 对股票走向的含义 / 要注意 / 当前这只票的真实数据,
 * 底部固定一句免责 —— 形态只是辅助信号,不构成独立买卖依据。
 */

/** 类型胶囊配色:红=偏多、绿=偏空、琥珀=预警/变盘前兆、灰=中性 */
const KIND_CLS: Record<SignalTermKind, string> = {
  bull: 'text-up bg-up/10 border-up/30',
  bear: 'text-down bg-down/10 border-down/30',
  squeeze: 'text-warn bg-warn/10 border-warn/30',
  warn: 'text-warn bg-warn/10 border-warn/30',
  neutral: 'text-text-sec bg-bg-subtle border-border-def',
  info: 'text-info bg-info/10 border-info/30',
};

export function SignalExplainCard({
  name,
  entry,
  nowLine,
  reason,
  style,
}: {
  /** 标记名(去掉 emoji) */
  name: string;
  /** 词典词条;缺失时只显示「暂无解释」,不猜不编 */
  entry: GlossaryEntry | null;
  /** 当前这只票的真实数据(只拼接口真有的字段) */
  nowLine: string | null;
  /**
   * 信号发生**当日**的数值依据(仅四类异动行为标注有)。
   *
   * ⚠️ 与 `nowLine` 是**两回事**,不可合并:
   * `nowLine` 是末根 K 线的当前值,`reason` 是信号当天的事实 ——
   * 混用会把 10-28 的信号配上 10-30 的现价,误导用户。
   */
  reason?: string | undefined;
  style: CSSProperties;
}) {
  return (
    <div
      role="tooltip"
      data-testid="signal-explain-card"
      className="w-[330px] rounded-md border border-border-str bg-bg-elevated p-3 shadow-xl"
      style={style}
    >
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-text-pri">{name}</span>
        {entry?.kindLabel && (
          <span
            className={clsx(
              'rounded-full border px-1.5 py-px text-[10px] font-medium leading-4',
              KIND_CLS[entry.kind ?? 'neutral'],
            )}
          >
            {entry.kindLabel}
          </span>
        )}
      </div>

      {entry ? (
        <>
          <div className="mt-2">
            <div className="text-[10px] tracking-wide text-text-ter">这是什么</div>
            <div className="mt-0.5 text-xs leading-relaxed text-text-sec">{entry.what}</div>
          </div>
          <div className="mt-2">
            <div className="text-[10px] tracking-wide text-text-ter">对股票走向的含义</div>
            <div className="mt-0.5 text-xs font-medium leading-relaxed text-text-pri">
              {entry.soWhat}
            </div>
          </div>
          {entry.watch && (
            <div className="mt-2">
              <div className="text-[10px] tracking-wide text-text-ter">要注意</div>
              <div className="mt-0.5 text-xs leading-relaxed text-text-sec">{entry.watch}</div>
            </div>
          )}
        </>
      ) : (
        <div className="mt-2 text-xs leading-relaxed text-text-sec">
          暂无解释(词条缺失,不做猜测)。
        </div>
      )}

      {reason && (
        <div className="mt-2">
          <div className="text-[10px] tracking-wide text-text-ter">当日依据</div>
          <div className="mt-0.5 text-[11px] leading-relaxed text-text-sec">
            {reason}
          </div>
        </div>
      )}

      {nowLine && (
        <div className="mt-2.5 border-t border-dashed border-border-str pt-2 text-[11px] leading-relaxed text-text-ter">
          {nowLine}
        </div>
      )}

      <div className="mt-2 text-[10.5px] leading-relaxed text-text-ter/80">
        形态只是辅助信号,不构成独立买卖依据。
      </div>
    </div>
  );
}
