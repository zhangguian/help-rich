import clsx from 'clsx';

import { decimalFormat, intFormat, priceFormat } from '@/lib/decimalFormat';
import type {
  ReviewTDirection,
  ReviewVerdict,
  TradeReviewResponse,
} from '@/lib/types';

/**
 * 拟交易复核(v0.6 · POST /api/calculator/review)—— 布局优化版
 *
 * 四个组件,对应计算器弹窗的四段:
 * - VerdictBar     ① 结论条(全宽置顶,打开即读)
 * - TAssessmentCard ③ 做 T 判断
 * - WhyPanel      ③ 判定依据(支持/反对左右两列并排)
 * - ReviewChecks  ④ 价位 / 数量检查条
 *
 * 配色约定(项目铁律,见 frontend/src/styles/tokens.css):
 * - 判定徽章只用**语义色**:success(绿) / warn(琥珀) / danger(红) / ❓warn+虚线
 * - 行情色 up/down 只出现在**价格语境**(价格水平、买/卖方向),绝不用于判定徽章
 *
 * 关于「买入=绿 / 卖出=红」:
 * 本 App 既有约定是 买入→text-down(绿)、卖出→text-up(红)
 * (见 CalculatorPanel 的方向单选、TransactionTable 的操作列)。
 * 判定卡与它们同屏,必须一致 —— 所以这里跟随 App 既有约定,
 * 而不是视觉稿里 A 股直觉的「买红卖绿」。要改口径只需改下面 ACT_CLS 一处。
 */
const ACT_CLS = {
  buy: 'text-down',
  sell: 'text-up',
} as const;

const VERDICT_META: Record<
  ReviewVerdict,
  {
    label: string;
    mark: string;
    badgeCls: string;
    borderCls: string;
  }
> = {
  ok: {
    label: '符合条件',
    mark: '✓',
    badgeCls: 'bg-success-bg text-success border-success/30',
    borderCls: 'border-l-success',
  },
  conditional: {
    label: '有条件可做',
    mark: '!',
    badgeCls: 'bg-warn-bg text-warn border-warn/30',
    borderCls: 'border-l-warn',
  },
  not_recommended: {
    label: '不建议',
    mark: '✕',
    badgeCls: 'bg-danger-bg text-danger border-danger/30',
    borderCls: 'border-l-danger',
  },
  unknown: {
    label: '数据不足',
    mark: '?',
    badgeCls: 'bg-transparent text-warn border-dashed border-text-ter',
    borderCls: 'border-l-dashed border-l-text-ter',
  },
};

export interface ReviewProps {
  review: TradeReviewResponse;
  action: 'buy' | 'sell';
  shares: number;
  price: string;
  code: string;
  name?: string | null | undefined;
  /** 账户可用资金(输入框当前值) */
  cash?: string;
  /** 账户可用资金变更回调(不传则输入框只读) */
  onCashChange?: (v: string) => void;
  /** 可用资金保存中 */
  cashSaving?: boolean;
  /** 可用资金已保存 */
  cashSaved?: boolean;
}

/**
 * `your_leg` → 中文标签
 *
 * 后端给的是 `reverse.sell` / `reverse.buyback` / `forward.buy` / `forward.sell`,
 * 这里翻成人话。未知值原样显示(不猜、不吞)。
 */
const LEG_LABEL: Record<string, string> = {
  'reverse.sell': '卖出腿',
  'reverse.buyback': '买回腿',
  'forward.buy': '买入腿',
  'forward.sell': '卖出腿',
};

/**
 * ① 结论条 —— 「这笔操作是否合适」
 *
 * 左:档位徽章 + 股票 + 操作;中:结论正文;右:风险 / 降级 chips。
 * 降级用**虚线中性** chip,与风险的实线琥珀 chip 区分 ——
 * 「数据缺了一块」不等于「有风险」,混在一起会让人误判。
 */
export function VerdictBar({ review, action, shares, price, code, name }: ReviewProps) {
  const meta = VERDICT_META[review.verdict];
  // 后端 headline 自带档位前缀(如「有条件可做 · …」),剥掉避免与徽章重复
  const headline = review.headline.startsWith(meta.label)
    ? review.headline.slice(meta.label.length).replace(/^\s*·\s*/, '')
    : review.headline;

  return (
    <div
      className={clsx(
        'flex items-start justify-between gap-4 px-3.5 py-2.5 rounded-lg',
        'bg-bg-elevated border border-border-def border-l-[3px]',
        meta.borderCls,
      )}
    >
      <div className="flex items-start gap-3 min-w-0">
        <span
          className={clsx(
            'shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-[13px] font-bold',
            meta.badgeCls,
          )}
        >
          {meta.mark} {meta.label}
        </span>
        <div className="min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-sm font-semibold truncate">{name ?? code}</span>
            <span className="font-mono text-xs text-text-ter">{code}</span>
            <span className={clsx('text-[13px] font-semibold font-mono', ACT_CLS[action])}>
              {action === 'buy' ? '买入' : '卖出'} {intFormat(shares)} @ {price}
            </span>
          </div>
          <div className="text-[13.5px] text-text-pri mt-0.5">{headline}</div>
        </div>
      </div>

      {(review.riskFlags.length > 0 || review.degraded.length > 0) && (
        <div className="shrink-0 flex flex-wrap gap-1.5 justify-end max-w-[340px]">
          {review.riskFlags.map((f, i) => (
            <span
              key={`risk-${i}`}
              className="text-[11px] px-1.5 py-0.5 rounded-xs border border-warn/40 bg-warn-bg text-warn whitespace-nowrap"
            >
              {f}
            </span>
          ))}
          {review.degraded.map((d, i) => (
            <span
              key={`deg-${i}`}
              className="text-[11px] px-1.5 py-0.5 rounded-xs border border-dashed border-border-str text-text-ter whitespace-nowrap"
              title="数据降级:该维度缺数据,没有编造数字"
            >
              {d}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * ③ 做 T 判断 —— 正T / 反T 两行对照 + 推荐
 *
 * 为什么换成两行对照:
 * 原来只有「适合 / 不适合做 T」一个结论,用户真正要问的是
 * 「做哪种 T」「能做多少股」。反T(先卖后买)与正T(先买后卖)的
 * 差别只有两点 —— 顺序、以及正T 要占用买入资金。
 *
 * 展示规则:
 * - **两个方向都显示** —— 不适用的那行灰显 + 写明原因,不隐藏
 *   (用户需要知道「还有另一个方向存在,只是当前不满足条件」)
 * - 推荐的��向用 accent 描边 + 「更适合」标签
 * - 股数上限算不出来时显示「—」,不显示 0(0 会被读成「一股都不能做」)
 *
 * 配色约定(项目铁律,见 frontend/src/styles/tokens.css):
 * - 判定徽章只用**语义色**:success(绿) / warn(琥珀) / danger(红) / ❓warn+虚线
 * - 行情色 up/down 只出现在**价格语境**(价格水平、买/卖方向),绝不用于判定徽章
 * - accent(青)只给选中/焦点 —— 这里用于「推荐方向」
 */
export function TAssessmentCard({
  review,
  action,
  shares,
  price,
  code,
  name,
  cash,
  onCashChange,
  cashSaving,
  cashSaved,
}: ReviewProps) {
  const t = review.tAssessment;
  const td = review.tDirections;
  const yourPrice = review.priceCheck.yourPrice;
  const hi = t.tHigh;
  const lo = t.tLow;
  const showRange = t.suitable && hi != null && lo != null && hi > lo;

  // 你的价在区间内 / 区间上方 / 区间下方
  let markPct: number | null = null;
  let markOutside: 'high' | 'low' | null = null;
  if (showRange && hi != null && lo != null && yourPrice != null) {
    if (yourPrice >= lo && yourPrice <= hi) {
      markPct = ((yourPrice - lo) / (hi - lo)) * 100;
    } else if (yourPrice > hi) {
      markOutside = 'high';
    } else {
      markOutside = 'low';
    }
  }

  const anyApplicable = td.reverse.applicable || td.forward.applicable;

  return (
    <div className="bg-bg-elevated border border-border-def rounded-lg px-3.5 py-3" data-testid="t-card">
      <div className="flex items-center justify-between gap-3 mb-2.5">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="text-[13px] font-semibold">做 T 判断</span>
          <span className="font-mono text-xs text-text-ter truncate">{code}</span>
          <span className={clsx('text-xs font-medium font-mono', ACT_CLS[action])}>
            {action === 'buy' ? '买入' : '卖出'} {intFormat(shares)} @ {price}
          </span>
        </div>
        <span
          className={clsx(
            'shrink-0 inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full border text-xs font-semibold',
            t.suitable
              ? 'bg-success-bg text-success border-success/30'
              : 'bg-warn-bg text-warn border-warn/30',
          )}
        >
          {t.suitable ? '✓ 适合做 T' : '! 当前不适合做 T'}
        </span>
      </div>

      {/* T 区间标尺(只在适合做 T 时有意义) */}
      {showRange && (
        <div className="grid grid-cols-[auto_1fr_auto] items-center gap-3 my-3" data-testid="t-range">
          <div className="text-center">
            <div className="text-[11px] text-text-ter">T 低点(买回)</div>
            <div className="font-mono text-lg font-bold text-down">{priceFormat(lo)}</div>
          </div>
          <div className="relative">
            <div className="relative h-2 rounded-full bg-bg-subtle border border-border-def">
              <div className="absolute inset-0 rounded-full bg-gradient-to-r from-success/30 to-warn/30" />
              {markPct != null && (
                <div
                  className="absolute -top-1 w-[2px] h-4 bg-accent rounded-full"
                  style={{ left: `${markPct}%` }}
                />
              )}
              {markOutside === 'high' && (
                <div
                  className="absolute -top-1 w-[2px] h-4 rounded-full bg-text-ter"
                  style={{ left: 'calc(100% - 2px)' }}
                />
              )}
              {markOutside === 'low' && (
                <div className="absolute -top-1 w-[2px] h-4 rounded-full bg-text-ter left-[2px]" />
              )}
            </div>
            {markPct != null && (
              <span
                className="absolute top-full mt-1 -translate-x-1/2 text-[10px] text-accent whitespace-nowrap font-mono"
                style={{ left: `${markPct}%` }}
              >
                你的 {priceFormat(yourPrice)}
              </span>
            )}
            {markOutside === 'high' && (
              <span className="absolute top-full mt-1 right-0 text-[10px] text-text-ter whitespace-nowrap font-mono">
                你的 {priceFormat(yourPrice)} ↑
              </span>
            )}
            {markOutside === 'low' && (
              <span className="absolute top-full mt-1 left-0 text-[10px] text-text-ter whitespace-nowrap font-mono">
                你的 {priceFormat(yourPrice)} ↓
              </span>
            )}
          </div>
          <div className="text-center">
            <div className="text-[11px] text-text-ter">T 高点(卖出)</div>
            <div className="font-mono text-lg font-bold text-up">{priceFormat(hi)}</div>
          </div>
        </div>
      )}

      {/* 推荐条 —— 结论前置 */}
      {td.recommended ? (
        <div
          className="flex items-start gap-2 px-3 py-2 rounded-md bg-accent-subtle border border-accent/30 mb-2.5"
          data-testid="t-recommend"
        >
          <span className="shrink-0 text-[11px] font-bold px-2 py-0.5 rounded-sm bg-accent text-bg-base">
            更适合
          </span>
          <span className="text-[13px] text-text-pri leading-[1.5]">
            <b className="text-accent">
              {td.recommended === 'reverse' ? '反T · 先卖后买' : '正T · 先买后卖'}
            </b>
            {td.yourLeg && (
              <>
                　你拟的这笔在
                <b className="text-accent">{LEG_LABEL[td.yourLeg] ?? td.yourLeg}</b>
              </>
            )}
            。{td.recommendReason}
          </span>
        </div>
      ) : (
        <div
          className="flex items-start gap-2 px-3 py-2 rounded-md bg-bg-subtle border border-border-def mb-2.5"
          data-testid="t-recommend"
        >
          <span className="shrink-0 text-[11px] font-bold px-2 py-0.5 rounded-sm bg-bg-subtle text-text-ter border border-border-str">
            不适合做 T
          </span>
          <span className="text-[13px] text-text-sec leading-[1.5]">{td.recommendReason}</span>
        </div>
      )}

      {/* 两行对照 */}
      <div className="flex flex-col gap-2" data-testid="t-directions">
        <DirectionRow dir={td.reverse} recommended={td.recommended === 'reverse'} yourLeg={td.yourLeg} />
        <DirectionRow dir={td.forward} recommended={td.recommended === 'forward'} yourLeg={td.yourLeg} />
      </div>

      {/* 账户可用资金 —— 正T 的股数上限受它约束 */}
      {/* exactOptionalPropertyTypes:可选属性不能显式传 undefined → 用条件展开 */}
      <CashInput
        cash={cash ?? ''}
        needCash={td.forward.reasonCode === 'no_cash'}
        {...(onCashChange ? { onCashChange } : {})}
        {...(cashSaving !== undefined ? { saving: cashSaving } : {})}
        {...(cashSaved !== undefined ? { saved: cashSaved } : {})}
      />

      <p className="mt-2 text-[11.5px] text-text-ter leading-relaxed" data-testid="t-plus1">
        {td.tPlusOneNote}
      </p>

      {!anyApplicable && (
        <p className="mt-1.5 text-[11.5px] text-text-ter leading-relaxed">
          做 T 需要至少 <b className="text-text-sec">3%</b>{' '}
          的近 5 日平均振幅才有差价空间 —— 当前不满足,做 T 只会平白增加交易成本。
        </p>
      )}
    </div>
  );
}

/**
 * 单个方向的行(反T 或 正T)
 *
 * 不可用时:整行灰显 + 标签说明原因 + 「为什么不能做」。
 * `reasonCode === 'no_cash'` 时额外标「缺资金」——
 * 这一档是**可以补的**(填个钱就能用),与「无底仓」这类补不了的要用不同标签,
 * 否则用户会以为没救了。
 */
function DirectionRow({
  dir,
  recommended,
  yourLeg,
}: {
  dir: ReviewTDirection;
  recommended: boolean;
  yourLeg: string | null;
}) {
  const prefix = dir.key === 'reverse' ? 'reverse.' : 'forward.';
  return (
    <div
      className={clsx(
        'border rounded-md px-3 py-2',
        recommended
          ? 'border-accent bg-accent-subtle'
          : dir.applicable
            ? 'border-border-def bg-bg-subtle'
            : 'border-border-def bg-bg-subtle opacity-70',
      )}
      data-testid={`t-dir-${dir.key}`}
      data-applicable={dir.applicable ? 'true' : 'false'}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={clsx(
            'text-[13px] font-semibold',
            recommended ? 'text-accent' : dir.applicable ? 'text-text-pri' : 'text-text-ter',
          )}
        >
          {dir.label}
        </span>
        {recommended && (
          <span className="text-[10.5px] font-semibold px-1.5 py-0.5 rounded-sm bg-accent text-bg-base">
            更适合
          </span>
        )}
        {!dir.applicable && (
          <span className="text-[10.5px] px-1.5 py-0.5 rounded-sm border border-dashed border-border-str text-text-ter">
            当前不可用
          </span>
        )}
        {dir.reasonCode === 'no_cash' && (
          <span className="text-[10.5px] px-1.5 py-0.5 rounded-sm border border-warn/40 bg-warn-bg text-warn">
            缺资金
          </span>
        )}
        {dir.reasonCode === 'cash_too_little' && (
          <span className="text-[10.5px] px-1.5 py-0.5 rounded-sm border border-warn/40 bg-warn-bg text-warn">
            资金不足
          </span>
        )}
        <span className="ml-auto text-xs text-text-sec whitespace-nowrap">
          {dir.applicable && dir.maxShares != null ? (
            <>
              上限 <b className="font-mono font-semibold text-text-pri">{intFormat(dir.maxShares)}</b> 股
              {dir.maxAmount && (
                <span className="ml-1.5 text-text-ter font-mono">
                  ≈ ¥{decimalFormat(dir.maxAmount)}
                </span>
              )}
            </>
          ) : (
            <>
              上限 <b className="font-mono font-semibold text-text-ter">—</b>
            </>
          )}
        </span>
      </div>

      {dir.steps.length > 0 ? (
        <ol className="mt-1.5 space-y-1">
          {dir.steps.map((st, i) => {
            const hit = yourLeg === prefix + st.role;
            return (
              <li
                key={`${st.role}-${i}`}
                className={clsx(
                  'flex items-start gap-2 text-[12.5px] leading-[1.5]',
                  hit ? 'text-text-pri' : 'text-text-sec',
                )}
              >
                <span
                  className={clsx(
                    'shrink-0 mt-0.5 w-4 h-4 rounded-full inline-flex items-center justify-center',
                    'text-[10px] font-mono',
                    hit
                      ? 'bg-up-bg text-up border border-up/50'
                      : 'bg-bg-surface text-text-ter border border-border-str',
                  )}
                >
                  {hit ? '●' : i + 1}
                </span>
                <span className="min-w-0">
                  {st.text}
                  {hit && (
                    <span className="ml-1.5 text-[10.5px] px-1.5 py-0.5 rounded-sm border border-up/40 bg-up-bg text-up align-middle">
                      你拟的这笔
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      ) : null}

      <div className="mt-1.5 pt-1.5 border-t border-dashed border-border-str text-[11.5px] text-text-ter">
        <b className="text-text-sec">{dir.applicable ? '前提' : '为什么不能做'}</b> ·{' '}
        {dir.prerequisite}
      </div>
    </div>
  );
}

/**
 * 账户可用资金输入
 *
 * **为什么放在 T 卡里**:正T 的股数上限直接由它决定,填在这里最省事
 * (不用去设置页找)。反T 不占用额外资金,所以这个输入框不影响反T。
 *
 * 未填写时用琥珀色提示 —— 「缺资金」是可以补的,不是故障。
 */
function CashInput({
  cash,
  onCashChange,
  needCash,
  saving,
  saved,
}: {
  cash: string;
  onCashChange?: (v: string) => void;
  needCash: boolean;
  saving?: boolean;
  saved?: boolean;
}) {
  return (
    <div
      className={clsx(
        'flex items-center gap-2 flex-wrap mt-2.5 px-3 py-2 rounded-md border',
        needCash ? 'border-warn/50 bg-warn-bg' : 'border-border-def bg-bg-subtle',
      )}
      data-testid="cash-input"
    >
      <label
        className={clsx(
          'text-xs inline-flex items-center gap-1 whitespace-nowrap',
          needCash ? 'text-warn font-semibold' : 'text-text-sec',
        )}
        htmlFor="t-available-cash"
      >
        {needCash ? '⚠ 未填写账户可用资金' : '账户可用资金'}
      </label>
      <input
        id="t-available-cash"
        type="number"
        min={0}
        step={1000}
        inputMode="decimal"
        value={cash}
        onChange={(e) => onCashChange?.(e.target.value)}
        placeholder="例如 20000"
        className="w-32 px-2 py-1 border border-border-def rounded-sm font-mono bg-bg-surface text-text-pri focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/30 transition-colors placeholder:text-text-ter/60"
      />
      <span className="text-[11.5px] text-text-ter">
        影响正T 的股数上限(反T 不占用额外资金)
      </span>
      {saving ? (
        <span className="text-[11px] text-text-ter">保存中...</span>
      ) : saved ? (
        <span className="text-[11px] text-success">已保存</span>
      ) : null}
    </div>
  );
}

/**
 * ③ 判定依据 —— 支持 / 反对 左右两列并排
 *
 * 为什么并排:原来两块纵向堆叠,理由一多就把页面拉长,读到最后要滚回去对照。
 */
export function WhyPanel({ review }: { review: TradeReviewResponse }) {
  const reasons = review.reasons;
  const blockers = review.blockers;
  return (
    <div className="mt-3" data-testid="review-why">
      <div className="flex items-center gap-2 text-xs text-text-ter mb-2">
        <span>判定依据</span>
        <span className="font-mono text-text-sec">
          支持 {reasons.length} · 反对 {blockers.length}
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
        <ReasonGroup
          title="反对(✕)"
          items={blockers}
          mark="✕"
          markCls="text-danger"
          empty="没有反对理由"
        />
        <ReasonGroup
          title="支持(✓)"
          items={reasons}
          mark="✓"
          markCls="text-success"
          empty="没有支持这条操作的条件"
        />
      </div>
    </div>
  );
}

/**
 * ④ 检查条 —— 价位检查 / 数量检查
 *
 * 风险与降级不在这里重复(已在结论条的 chips 里)。
 */
export function ReviewChecks({ review }: { review: TradeReviewResponse }) {
  const pc = review.priceCheck;
  const sc = review.sizeCheck;
  const priceValue =
    pc.suggested != null
      ? `建议 ${priceFormat(pc.suggested)} · 你的 ${priceFormat(pc.yourPrice)}`
      : `无建议价 · 你的 ${priceFormat(pc.yourPrice)}`;
  const sizeValue =
    sc.suggestedShares != null
      ? `建议 ${intFormat(sc.suggestedShares)} 股 · 你的 ${intFormat(sc.yourShares)} 股`
      : `你的 ${intFormat(sc.yourShares)} 股`;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
      <CheckCell label="价位检查" value={priceValue} note={pc.note} />
      <CheckCell label="数量检查" value={sizeValue} note={sc.note} />
    </div>
  );
}

function ReasonGroup({
  title,
  items,
  mark,
  markCls,
  empty,
}: {
  title: string;
  items: string[];
  mark: string;
  markCls: string;
  empty: string;
}) {
  return (
    <div className="bg-bg-elevated border border-border-def rounded-md px-3 py-2.5">
      <div className="text-[11px] text-text-ter mb-1.5">{title}</div>
      {items.length === 0 ? (
        <div className="text-xs text-text-ter italic">{empty}</div>
      ) : (
        <ul className="space-y-1.5">
          {items.map((r, i) => (
            <li key={i} className="flex gap-2 text-[13px] text-text-sec leading-[1.5]">
              <span className={clsx('shrink-0 font-bold', markCls)}>{mark}</span>
              <span className="min-w-0">{r}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CheckCell({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="bg-bg-elevated border border-border-def rounded-md px-3 py-2.5">
      <div className="text-[11px] text-text-ter">{label}</div>
      <div className="text-[13px] text-text-pri font-mono mt-0.5">{value}</div>
      {note ? <div className="text-[11.5px] text-text-sec mt-1">{note}</div> : null}
    </div>
  );
}
