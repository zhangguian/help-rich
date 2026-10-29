'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { PlanItemList } from '@/components/plan/PlanItemList';
import { OutlookCard } from '@/components/plan/OutlookCard';
import { ReviewCard } from '@/components/plan/ReviewCard';
import { StockAnchorRail } from '@/components/plan/StockAnchorRail';
import {
  fetchBattlePlan,
  fetchBattlePlanScope,
  generateBattlePlan,
} from '@/lib/api/advanced';
import type {
  BattlePlan,
  BattlePlanScopeResponse,
  BattlePlanUniverse,
} from '@/lib/planTypes';
import {
  aggregateStockFulfillment,
  buildRailGroups,
  type StockFulfillment,
} from '@/lib/planDerive';

type State =
  | { kind: 'loading' }
  | { kind: 'empty'; message: string }
  | { kind: 'ready'; plan: BattlePlan }
  | { kind: 'error'; message: string }
  | { kind: 'generating' };

/** 后端 detail 才是人话;axios 的 e.message 只是 "Request failed with status code 404" */
function messageOf(e: unknown): string {
  const anyE = e as { response?: { data?: { detail?: unknown } } } | null;
  const d = anyE?.response?.data?.detail;
  if (typeof d === 'string' && d) return d;
  return e instanceof Error ? e.message : String(e);
}

/** 用 HTTP status 判定 404,不靠字符串匹配 */
function statusOf(e: unknown): number | undefined {
  return (e as { response?: { status?: number } } | null)?.response?.status;
}

/** 昨天的日期(YYYY-MM-DD)—— 空态用它说明「复盘闭环从哪一天开始生效」 */
function yesterdayIso(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 空态要讲清楚的三段内容 —— 生成后页面上就是这三块,不是「生成完你就知道了」 */
const THREE_SECTIONS = [
  {
    no: '①',
    title: '今日复盘',
    body: '把昨天的每条预案拿来对今天的成交与行情:执行了记「已执行」,价位偏离超 3% 会写明成交价与触发价;当天没碰到价位的记「未触发」,不评价对错。',
  },
  {
    no: '②',
    title: '明日市场预期',
    body: '按量能、涨跌家数、均线位置、板块资金四个维度做规则推断,给出上证关键位 —— 只写「倾向」,不预测涨跌。',
  },
  {
    no: '③',
    title: '明日逐票操作预案',
    body: '每条写死:什么价位、什么条件、做什么动作、依据是什么、什么情况下作废;拿不到数据的条目如实标注,不用假数据补齐。',
  },
] as const;

/** 拿到计划之后怎么用 —— 空态不该只留一句「点按钮」 */
const HOW_TO_USE = [
  '收盘后生成今天的计划 —— 里面写的是「明天什么价位做什么」,不是「今天买什么」。',
  '明天再来时,「今日复盘」会把昨天的每条预案逐条对照今天的成交与行情。',
  '缺数据、写不了判定的条目会标「未判定」,不会被当成「没兑现」糊弄过去。',
  '池里的票达到预期就留着,连续 3 天没达预期会被换掉 —— 换掉的理由会留在左栏。',
] as const;

export function PlanPanel() {
  const [state, setState] = useState<State>({ kind: 'loading' });
  /** /scope:空态要摊开「选股口径 + 当前池」,也要现价 */
  const [scopeInfo, setScopeInfo] = useState<BattlePlanScopeResponse | null>(null);
  /**
   * /scope 的加载状态
   *
   * ⚠️ 必须区分「还在加载」与「拿不到」——
   * `/scope` 要统计全市场口径,冷启动时可能要几秒。
   * 若两者都显示「快照暂不可用」,用户会以为坏了;
   * 若两者都显示空数字,用户会以为没有票。
   */
  const [scopeStatus, setScopeStatus] = useState<'loading' | 'ready' | 'failed'>('loading');
  /** 昨天的日报是否已生成 —— 空态用它说明「复盘闭环从哪一天开始生效」 */
  const [yesterdayPlan, setYesterdayPlan] = useState<{ date: string; exists: boolean } | null>(
    null,
  );
  /** 左栏点击 → 中栏聚焦的那只票 */
  const [activeCode, setActiveCode] = useState<string | null>(null);

  const loadScope = useCallback(async () => {
    setScopeStatus('loading');
    try {
      setScopeInfo(await fetchBattlePlanScope());
      setScopeStatus('ready');
    } catch {
      setScopeInfo(null);
      setScopeStatus('failed');
    }
  }, []);

  const load = useCallback(async () => {
    setState({ kind: 'loading' });
    void loadScope();
    try {
      const plan = await fetchBattlePlan();
      setState({ kind: 'ready', plan });
    } catch (e) {
      if (statusOf(e) === 404) {
        setState({ kind: 'empty', message: '今天的作战计划还没生成' });
      } else {
        setState({ kind: 'error', message: messageOf(e) });
      }
    }
  }, [loadScope]);

  useEffect(() => {
    void load();
  }, [load]);

  // 空态:查一下昨天的日报在不在 —— 有,「今日复盘」明天就有对照物;没有,就是第一次用
  useEffect(() => {
    if (state.kind !== 'empty') return;
    let alive = true;
    const iso = yesterdayIso();
    void fetchBattlePlan(iso)
      .then((p) => {
        if (alive) setYesterdayPlan({ date: p.planDate, exists: true });
      })
      .catch(() => {
        // 404 = 昨天还没生成(正常业务语义,fetchBattlePlan 已静音该 404 的 toast)
        if (alive) setYesterdayPlan({ date: iso, exists: false });
      });
    return () => {
      alive = false;
    };
  }, [state.kind]);

  const generate = useCallback(async () => {
    setState({ kind: 'generating' });
    void loadScope();
    try {
      const plan = await generateBattlePlan();
      setState({ kind: 'ready', plan });
    } catch (e) {
      setState({ kind: 'error', message: messageOf(e) });
    }
  }, [loadScope]);

  /**
   * 左栏锚点 → 中栏那只票(滚动 + 高亮)
   *
   * ⚠️ 不能用 `el.scrollIntoView()` —— 它会连带滚动**所有**可滚动祖先,
   * 包括左栏那个 `overflow-y-auto` 容器 → 点一只票,左栏的锚点列表反而被推走了
   * (用户点了票却把自己的清单滚没了)。这里只滚外层 `main`。
   *
   * ⚠️ 有的票**没有**预案条目(决策层拿不到数据 → 被跳过)。
   * 这种票点下去不能静默无反应 —— 锚点行自身高亮,表示「选中了这只」。
   */
  const handleSelect = useCallback((code: string) => {
    setActiveCode(code);
    const el = document.getElementById(`plan-stock-${code}`);
    if (!el) return;
    const main = el.closest('main');
    if (!main) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    const offset =
      el.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop;
    main.scrollTo({ top: Math.max(0, offset - 96), behavior: 'smooth' });
  }, []);

  // ⚠️ 这两个 useMemo 必须留在**所有提前 return 之前** ——
  // Hooks 不能条件调用,放在 `if (state.kind === 'loading') return` 之后
  // 会让「加载态 → 就绪态」切换时少调一次 Hook,React 直接报
  // 「Rendered fewer hooks than expected」。
  const plan = state.kind === 'ready' ? state.plan : null;

  /** 昨日股票级兑现(池与锚点栏共用同一份判定) */
  const fulfillment: Map<string, StockFulfillment> = useMemo(
    () => aggregateStockFulfillment(plan?.review?.fulfillment?.items),
    [plan],
  );

  const railGroups = useMemo(
    () =>
      buildRailGroups(
        plan?.meta.scope,
        plan?.meta.pool ?? null,
        plan?.meta.quotes,
        plan?.items,
        fulfillment,
      ),
    [plan, fulfillment],
  );

  if (state.kind === 'loading') {
    return (
      <div className="space-y-3">
        <Card>
          <div className="h-4 w-40 animate-pulse rounded bg-bg-subtle" />
          <div className="mt-3 h-3 w-full animate-pulse rounded bg-bg-subtle" />
          <div className="mt-2 h-3 w-3/4 animate-pulse rounded bg-bg-subtle" />
        </Card>
      </div>
    );
  }

  if (state.kind === 'generating') {
    return <GeneratingPanel scope={scopeInfo} />;
  }

  if (state.kind === 'error') {
    return (
      <Card>
        <h3 className="text-sm font-semibold">生成失败</h3>
        <p className="mt-2 text-xs text-text-sec">{state.message}</p>
        <Button variant="secondary" size="sm" className="mt-3" onClick={() => void generate()}>
          重试
        </Button>
      </Card>
    );
  }

  if (state.kind === 'empty') {
    return (
      <EmptyPanel
        message={state.message}
        scope={scopeInfo}
        scopeStatus={scopeStatus}
        yesterdayPlan={yesterdayPlan}
        onGenerate={() => void generate()}
      />
    );
  }

  if (!plan) return null;

  const meta = plan.meta;
  const pool = meta.pool ?? null;

  const poolCodes = new Set((pool?.members ?? []).map((m) => m.stockCode));
  const watchlistCount = meta.scope.filter((s) => !poolCodes.has(s.stockCode)).length;
  const poolCount = pool?.members.length ?? 0;
  /** 各阶段耗时之和 ≈ 整轮生成耗时(阶段是串行的) */
  const genSeconds = meta.timings
    ? Object.values(meta.timings).reduce((a, b) => a + b, 0)
    : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">作战计划</h2>
          <p className="mt-0.5 text-[11px] text-text-ter">
            {plan.planDate} · 覆盖 {meta.scopeCount} 只(自选 {watchlistCount} + 全市场池{' '}
            {poolCount})
            {plan.targetDate
              ? ` · 目标日 ${plan.targetDate}${meta.targetDateEstimated ? '(按工作日推算)' : ''}`
              : ''}
            {genSeconds != null ? ` · 生成耗时 ${genSeconds.toFixed(1)}s` : ''}
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => void generate()}>
          重新生成
        </Button>
      </div>

      {meta.degraded && (meta.degradedReason ?? []).length > 0 && (
        <div
          data-testid="plan-degraded"
          className="rounded border border-warn/40 bg-warn-bg px-3 py-2 text-[11px] text-warn"
        >
          部分数据缺失（已如实标注，未用假数据填补）：
          {meta.degradedReason.join('；')}
        </div>
      )}

      {meta.truncated && (
        <div className="rounded border border-warn/40 bg-warn-bg px-3 py-2 text-[11px] text-warn">
          覆盖数量超过单次上限,已按「先砍池尾 → 再砍★关注尾 → 持仓永不砍」截断,
          超出部分本次不做预案。
        </div>
      )}

      {/* 三栏工作台
          ⚠️ 断点用 lg(1024),不用 xl(1280) —— spec §5.2 铁律「两栏保持到 1024px」,
          三栏版同样在 1024 才折叠
          ⚠️ 栅格数值复用 v0.8 交易台的同一套母体(左 236 / 中自适应 / 右 268),
          不另起一套宽度

          窄屏(<1024)单栏顺序:预期 → 锚点 → 预案 → 复盘。
          实现:左栏容器在窄屏用 `display:contents`「透明」成两个独立 grid item,
          宽屏再变回纵向 flex 容器(与既有右栏写法同一手法)。 */}
      <div
        data-testid="plan-grid"
        className="grid grid-cols-1 gap-3 lg:grid-cols-[236px_minmax(0,1fr)_268px] lg:items-start xl:grid-cols-[252px_minmax(0,1fr)_304px]"
      >
        {/* 左栏:股票锚点栏 + 今日复盘(窄屏时 contents → 两个独立 item)

            ⚠️ 桌面档**吸顶固定**:中栏是 19 张票卡的长列表,页面一滚,
            左栏跟着滚走就等于丢了「今天盯哪些票」——视线要来回拉回顶部。
            ⚠️ 左栏内容(22 只票)通常**比视口高**,所以不能只加 sticky:
            纯 sticky 的超高元素底部永远够不着(它会一直贴在 top)。
            正确做法 = sticky + 限高 + 栏内滚动(外层页面滚中栏,左栏自己滚)。 */}
        <div className="contents lg:col-start-1 lg:row-start-1 lg:flex lg:flex-col lg:gap-3 lg:sticky lg:top-3 lg:max-h-[calc(100vh-1.5rem)] lg:overflow-y-auto">
          <div className="order-2 lg:order-none">
            <StockAnchorRail
              groups={railGroups}
              onSelect={handleSelect}
              activeCode={activeCode}
            />
          </div>
          <div className="order-4 lg:order-none">
            <ReviewCard review={plan.review ?? null} />
          </div>
        </div>

        {/* 中栏:逐票作战计划(主体,宽度不能被压) */}
        <div className="order-3 lg:order-none lg:col-start-2 lg:row-start-1">
          <PlanItemList
            items={plan.items ?? []}
            targetDate={plan.targetDate ?? null}
            scope={meta.scope}
            pool={pool}
            fulfillment={fulfillment}
            activeCode={activeCode}
          />
        </div>

        {/* 右栏:明日市场预期(窄屏排最前 —— 当天的大盘前提) */}
        <div className="order-1 lg:order-none lg:col-start-3 lg:row-start-1 lg:sticky lg:top-3">
          <OutlookCard outlook={plan.outlook} />
        </div>
      </div>
    </div>
  );
}

/* ============================================================
 * 空态(今天还没生成)
 * ============================================================ */

function EmptyPanel({
  message,
  scope,
  scopeStatus,
  yesterdayPlan,
  onGenerate,
}: {
  message: string;
  scope: BattlePlanScopeResponse | null;
  scopeStatus: 'loading' | 'ready' | 'failed';
  yesterdayPlan: { date: string; exists: boolean } | null;
  onGenerate: () => void;
}) {
  const watchlist = scope?.watchlist ?? [];
  const pool = scope?.pool ?? [];
  const universe = scope?.universe ?? null;

  return (
    <div data-testid="plan-empty" className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_300px]">
      <Card>
        <h3 className="text-sm font-semibold">{message}</h3>
        <p className="mt-1.5 text-xs text-text-sec">
          生成后会得到三段内容：① 今日复盘（昨日预案兑现了没有）② 明日市场预期（四维度规则推断）
          ③ 明日逐票操作预案（什么价位做什么）。
        </p>
        <Button className="mt-2.5" size="sm" onClick={onGenerate}>
          生成今日计划
        </Button>

        {/* 选股口径写明白 —— 不写「全市场选股」这种含糊说法 */}
        <div className="mt-3 border-t border-border-def pt-2.5">
          <div className="text-[11px] text-text-ter">本次选股口径</div>
          {universe ? (
            <ul className="mt-1.5 space-y-1 text-[11px] leading-relaxed">
              <li>
                <span className="font-semibold text-text-pri">全市场 {universe.total} 只</span>
                {' → '}沪深主板 {universe.mainBoard} 只（排除创业板 / 科创板 / 北交所）
              </li>
              <li>
                剔除 ST / *ST 后 {universe.nonSt} 只 → 成交额 ≥ {universe.minAmountYi} 亿后{' '}
                <span className="font-semibold text-text-pri">{universe.afterFilters} 只</span>
              </li>
              <li>
                滚动池 <span className="font-semibold text-text-pri">5 只</span>:达到预期就留在池里,
                连续 3 天未达预期就剔除并由新股票补位
              </li>
            </ul>
          ) : scopeStatus === 'loading' ? (
            /* ⚠️ 「还在统计」与「统计不出来」是两回事 —— 冷启动时 /scope 要拉全市场快照,
               可能要几秒。此时说「不可用」会让用户以为坏了。 */
            <p className="mt-1.5 text-[11px] text-text-sec">正在统计全市场口径…</p>
          ) : (
            <p className="mt-1.5 text-[11px] text-text-sec">
              全市场快照暂不可用 —— 无法给出选股口径统计(生成时会如实标注降级原因)。
            </p>
          )}
        </div>

        {/* 当前滚动池:让人看见「池里现在是谁」 */}
        <div className="mt-3 border-t border-border-def pt-2.5">
          <div className="text-[11px] text-text-ter">当前滚动池({pool.length} 只)</div>
          {scopeStatus === 'loading' ? (
            <p className="mt-1.5 text-[11px] text-text-sec">正在读取池状态…</p>
          ) : pool.length === 0 ? (
            <p className="mt-1.5 text-[11px] text-text-sec">
              池里还没有票 —— 第一次生成时会从全市场选出 5 只补位。
            </p>
          ) : (
            <ul className="mt-1.5 space-y-0.5">
              {pool.map((m) => (
                <li key={m.stockCode} className="text-[11px] text-text-sec">
                  <span className="font-semibold text-text-pri">{m.stockName ?? m.stockCode}</span>
                  <span className="ml-1 font-mono text-[10px] text-text-ter">{m.stockCode}</span>
                  {m.missStreak > 0 && (
                    <span className="ml-1 text-warn">连续 {m.missStreak} 天未达预期</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* 空态不留大片虚空:把「明天要看哪些票」摆出来 */}
        <div className="mt-3 border-t border-border-def pt-2.5">
          <div className="text-[11px] text-text-ter">
            自选股票池（持仓 ∪ ★关注）· 共 {watchlist.length} 只
          </div>
          {scopeStatus === 'loading' ? (
            <p className="mt-1.5 text-[11px] text-text-sec">正在读取自选与持仓…</p>
          ) : watchlist.length === 0 ? (
            <p className="mt-1.5 text-[11px] text-text-sec">
              还没有持仓也没有★关注票 —— 先在「盯盘台」加自选或建一笔持仓,作战计划才有对象。
            </p>
          ) : (
            <ul className="mt-1.5 grid grid-cols-1 gap-x-4 gap-y-0.5 sm:grid-cols-2">
              {watchlist.map((s) => (
                <li key={s.stockCode} className="truncate py-0.5 text-[11px] text-text-pri">
                  {s.stockName ?? s.stockCode}
                  <span className="ml-1 font-mono text-[10px] text-text-ter">{s.stockCode}</span>
                  {s.inPosition && <span className="ml-1 text-text-sec">持仓</span>}
                  {s.isFavorite && <span className="ml-1 text-text-sec">★</span>}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* 空态不留大片虚空:说明复盘闭环从哪一天开始生效 */}
        <div className="mt-3 border-t border-border-def pt-2.5">
          <div className="text-[11px] text-text-ter">昨天的计划</div>
          {yesterdayPlan === null ? (
            <p className="mt-1.5 text-[11px] text-text-sec">正在查…</p>
          ) : yesterdayPlan.exists ? (
            <p className="mt-1.5 text-[11px] text-text-sec">
              {yesterdayPlan.date} 已生成 —— 生成今天的计划后,「今日复盘」会立刻对照昨天的预案
              逐条给出兑现情况（缺数据写「未判定」,不拿「没兑现」冒充）。
            </p>
          ) : (
            <p className="mt-1.5 text-[11px] text-text-sec">
              {yesterdayPlan.date} 还没有计划 —— 这是第一次生成,复盘闭环从明天的计划开始生效。
            </p>
          )}
        </div>

        {/* 空态不留大片虚空:把「怎么用」讲清楚,别让用户拿到计划后不知道下一步 */}
        <div className="mt-3 border-t border-border-def pt-2.5">
          <div className="text-[11px] text-text-ter">怎么用</div>
          <ul className="mt-1 space-y-0.5">
            {HOW_TO_USE.map((t) => (
              <li key={t} className="text-[11px] leading-relaxed text-text-sec">
                {t}
              </li>
            ))}
          </ul>
        </div>
      </Card>

      <div className="space-y-3">
        <Card>
          <h3 className="text-sm font-semibold">明日市场预期</h3>
          <p className="mt-1.5 text-xs text-text-sec">
            生成时会按量能、涨跌家数、均线位置、板块资金四个维度做规则推断,并给出上证关键位 ——
            只写「倾向」,不预测涨跌。
          </p>
        </Card>
        <Card>
          <h3 className="text-sm font-semibold">明日逐票操作预案</h3>
          <p className="mt-1.5 text-xs text-text-sec">
            每条预案都会写死:什么价位、什么条件、做什么动作、依据是什么、什么情况下作废。
          </p>
        </Card>
        <Card>
          <h3 className="text-sm font-semibold">今日复盘</h3>
          <p className="mt-1.5 text-xs text-text-sec">
            拿昨天的每条预案对照今天的成交与行情:执行了记「已执行」,价位偏离超 3% 会写明
            成交价与触发价;当天没碰到价位的记「未触发」—— 不评价对错。
          </p>
        </Card>
      </div>
    </div>
  );
}

/* ============================================================
 * 生成中(分阶段报进度)
 * ============================================================ */

/**
 * 生成中:按流水线分阶段显示
 *
 * ⚠️ 阶段是**按耗时推进的示意**,不是后端推来的进度 ——
 * 后端只有一个 POST /generate,没有进度通道。
 * 阶段文案里的只数是**真数据**(来自 /scope 的 universe),不是编的。
 */
function GeneratingPanel({ scope }: { scope: BattlePlanScopeResponse | null }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const t0 = Date.now();
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, []);

  const universe: BattlePlanUniverse | null = scope?.universe ?? null;
  const poolCount = scope?.pool.length ?? 0;
  const watchCount = scope?.watchlist.length ?? 0;

  // 阶段推进点(秒):全市场快照 → 主板过滤 → 4 因子打分 → 逐票预案
  const stages = [
    { at: 0, label: '全市场快照已就绪', detail: universe ? `${universe.total} 只` : '拉取中' },
    {
      at: 3,
      label: '主板过滤完成',
      detail: universe ? `→ ${universe.afterFilters} 只候选` : '过滤中',
    },
    { at: 8, label: '4 因子打分中', detail: '80 只精排' },
    {
      at: 15,
      label: '逐票生成预案',
      detail: `${watchCount + poolCount || '—'} 只票`,
    },
  ];
  const current = stages.filter((s) => elapsed >= s.at).length - 1;

  return (
    <Card data-testid="plan-generating">
      <h3 className="text-sm font-semibold">正在生成作战计划…</h3>
      <p className="mt-1.5 text-xs text-text-sec">
        从沪深全市场主板里筛出今天的滚动池,并算好 {watchCount + poolCount || '—'} 只票的明日预案。
      </p>

      <div className="mt-3 space-y-1.5">
        {stages.map((s, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <div key={s.label} className="flex items-center gap-2 text-[11.5px]">
              <span
                className={clsx(
                  'h-2 w-2 shrink-0 rounded-full',
                  done ? 'bg-down' : active ? 'animate-spin border-2 border-accent border-t-transparent' : 'bg-border-str',
                )}
                aria-hidden
              />
              <span className={active ? 'text-text-pri' : done ? 'text-text-sec' : 'text-text-ter'}>
                {s.label}
              </span>
              <span className="ml-auto font-mono text-[10.5px] text-text-ter">{s.detail}</span>
            </div>
          );
        })}
      </div>

      <div className="mt-3 h-[3px] overflow-hidden rounded bg-bg-subtle">
        <i
          className="block h-full bg-accent transition-[width] duration-500"
          style={{ width: `${Math.min(95, (elapsed / 35) * 100)}%` }}
        />
      </div>
      <p className="mt-1.5 text-[11px] text-text-ter">
        已用 {elapsed} 秒 · 预计还需 20~35 秒(覆盖 {watchCount + poolCount || '—'} 只票时)
      </p>
    </Card>
  );
}
