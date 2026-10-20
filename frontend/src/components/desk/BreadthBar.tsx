'use client';

import clsx from 'clsx';

import type { MarketSentiment } from '@/lib/types';

/**
 * 市场宽度条(v0.8 交易台的签名元素)
 *
 * **它回答什么**:今天是普涨,还是只有少数票在涨?
 * 旧版把涨跌家数做成三张独立数字卡,回答不了这个问题 ——
 * 「3777 家上涨」既可能是 68% 的票都涨(普涨),也可能是少数权重股拉指数
 * (结构性上涨),对操作的意义完全相反。
 *
 * **做法**:把全市场 5568 只按涨跌幅分 9 档,做成一条宽度按占比的色带。
 * A 股红涨绿跌,所以**绿在左(跌)、红在右(涨)**。
 * 昨收 → 今收的分布一眼可见:色带中间厚两边薄 = 温和分化;
 * 右侧红段特别长 = 普涨;左侧绿段长 = 普跌。
 *
 * **口径**:全市场翻页统计(沪深京 A 股),不是首页采样。
 * partial=true 时角标显式提示「采样」,不可作决策依据。
 */

export interface BreadthStats {
  upTotal: number | null;
  downTotal: number | null;
  flatTotal: number | null;
  amountYi: number | null;
  buckets: MarketSentiment['buckets'] | null;
  sampleSize: number | null;
  partial: boolean;
}

interface Segment {
  key: string;
  label: string;
  n: number;
  /** 色带底色 —— 用 RGB 通道变量的 alpha 阶梯,浅色主题自动跟随 */
  color: string;
}

/**
 * 9 段从左到右:跌停 → 平 → 涨停(绿跌左 / 红涨右)
 *
 * 颜色用 `rgb(var(--up-rgb) / α)` 形式而非写死 hex:
 * --up-rgb / --down-rgb 在 tokens.css 里随主题切换,这样色带在
 * 深色终端(亮红亮绿)与纸面终端(暗红暗绿)下都清晰。
 */
function buildSegments(b: MarketSentiment['buckets']): Segment[] {
  return [
    { key: 'limit_down', label: '跌停', n: b.limitDown, color: 'rgb(var(--down-rgb) / 0.88)' },
    { key: 'down_5_10', label: '-5~10', n: b.down5_10, color: 'rgb(var(--down-rgb) / 0.70)' },
    { key: 'down_1_5', label: '-1~5', n: b.down1_5, color: 'rgb(var(--down-rgb) / 0.48)' },
    { key: 'down_0_1', label: '-0~1', n: b.down0_1, color: 'rgb(var(--down-rgb) / 0.28)' },
    { key: 'flat', label: '平', n: b.flat, color: 'rgb(var(--neutral-rgb) / 0.55)' },
    { key: 'up_0_1', label: '0~1', n: b.up0_1, color: 'rgb(var(--up-rgb) / 0.28)' },
    { key: 'up_1_5', label: '1~5', n: b.up1_5, color: 'rgb(var(--up-rgb) / 0.48)' },
    { key: 'up_5_10', label: '5~10', n: b.up5_10, color: 'rgb(var(--up-rgb) / 0.70)' },
    { key: 'limit_up', label: '涨停', n: b.limitUp, color: 'rgb(var(--up-rgb) / 0.88)' },
  ];
}

export function BreadthBar({ stats }: { stats: BreadthStats | null }) {
  const b = stats?.buckets ?? null;
  const segments = b ? buildSegments(b) : null;
  const total = Math.max(stats?.sampleSize ?? 0, 1);

  return (
    <section
      className="shrink-0 bg-bg-elevated border-b border-border-def px-3 py-2"
      aria-label="市场宽度"
    >
      <div className="flex items-stretch gap-3 min-w-0">
        {/* 左:关键数字 */}
        <div className="flex items-baseline gap-3 shrink-0 flex-wrap">
          <Stat label="全A" value={stats?.sampleSize ?? null} unit="只" />
          <Stat label="涨" value={stats?.upTotal ?? null} tone="up" />
          <Stat label="跌" value={stats?.downTotal ?? null} tone="down" />
          {b && <Stat label="涨停" value={b.limitUp} tone="up" />}
          {b && <Stat label="跌停" value={b.limitDown} tone="down" />}
          {stats?.amountYi != null && (
            <Stat
              label="成交"
              value={Number((stats.amountYi / 10000).toFixed(2))}
              unit="万亿"
            />
          )}
          {stats?.partial && (
            <span
              className="text-warn text-[10px] font-mono"
              title="仅首页采样,数据不可作决策依据"
            >
              ⚠ 采样
            </span>
          )}
        </div>

        {/* 右:色带 + 图例 */}
        <div className="flex-1 min-w-0 flex flex-col gap-1 justify-center">
          {segments ? (
            <>
              <div
                className="flex h-3 rounded-xs overflow-hidden gap-px bg-bg-subtle"
                role="img"
                aria-label={`全市场涨跌分布:${segments.map((s) => `${s.label} ${s.n} 家`).join(',')}`}
              >
                {segments.map((s) => (
                  <div
                    key={s.key}
                    className="h-full transition-[filter] hover:brightness-125"
                    style={{ flex: `${Math.max((s.n / total) * 100, 0.4)}`, background: s.color }}
                    title={`${s.label} ${s.n} 家`}
                  />
                ))}
              </div>
              <div className="flex gap-3 flex-wrap overflow-hidden text-[9px] text-text-ter font-mono">
                {segments.map((s) => (
                  <span key={s.key} className="flex items-center gap-1 whitespace-nowrap">
                    <i
                      className="w-1.5 h-1.5 rounded-xs inline-block shrink-0"
                      style={{ background: s.color }}
                      aria-hidden
                    />
                    {s.label}
                    <b className="text-text-sec font-semibold">{s.n}</b>
                  </span>
                ))}
              </div>
            </>
          ) : (
            <div className="h-3 rounded-xs bg-bg-subtle animate-pulse" />
          )}
        </div>
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  unit,
  tone,
}: {
  label: string;
  value: number | null;
  unit?: string;
  tone?: 'up' | 'down';
}) {
  return (
    <span className="flex items-baseline gap-1 whitespace-nowrap">
      <span className="text-[10px] text-text-ter font-mono tracking-wider">{label}</span>
      <span
        className={clsx(
          'text-[15px] font-mono font-semibold tabular-nums',
          tone === 'up' && 'text-up',
          tone === 'down' && 'text-down',
          !tone && 'text-text-pri',
        )}
      >
        {value == null ? '--' : value.toLocaleString('zh-CN')}
      </span>
      {unit && <span className="text-[10px] text-text-ter">{unit}</span>}
    </span>
  );
}
