'use client';

import { useCallback, useEffect, useState } from 'react';

import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { PlanItemList } from '@/components/plan/PlanItemList';
import { OutlookCard } from '@/components/plan/OutlookCard';
import { ReviewCard } from '@/components/plan/ReviewCard';
import {
  fetchBattlePlan,
  fetchBattlePlanScope,
  generateBattlePlan,
} from '@/lib/api/advanced';
import type { BattlePlan } from '@/lib/planTypes';

type State =
  | { kind: 'loading' }
  | { kind: 'empty'; message: string }
  | { kind: 'ready'; plan: BattlePlan }
  | { kind: 'error'; message: string }
  | { kind: 'generating' };

type ScopeRow = {
  stockCode: string;
  stockName: string | null;
  inPosition: boolean;
  isFavorite: boolean;
};

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
] as const;

export function PlanPanel() {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [scope, setScope] = useState<ScopeRow[]>([]);
  /** 昨天的日报是否已生成 —— 空态用它说明「复盘闭环从哪一天开始生效」 */
  const [yesterdayPlan, setYesterdayPlan] = useState<{ date: string; exists: boolean } | null>(
    null,
  );

  const load = useCallback(async () => {
    setState({ kind: 'loading' });
    try {
      const plan = await fetchBattlePlan();
      setState({ kind: 'ready', plan });
    } catch (e) {
      if (statusOf(e) === 404) {
        setState({ kind: 'empty', message: '今天的作战计划还没生成' });
        // 空态也要有实质内容:顺手把目标股票池拉出来(顺便用上 /scope 端点)
        try {
          setScope(await fetchBattlePlanScope());
        } catch {
          setScope([]);
        }
      } else {
        setState({ kind: 'error', message: messageOf(e) });
      }
    }
  }, []);

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
    try {
      const plan = await generateBattlePlan();
      setState({ kind: 'ready', plan });
    } catch (e) {
      setState({ kind: 'error', message: messageOf(e) });
    }
  }, []);

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
    return (
      <Card>
        <h3 className="text-sm font-semibold">正在生成作战计划…</h3>
        <p className="mt-2 text-xs text-text-sec">
          正在采集持仓与关注票的行情、指标和市场环境,请稍候（约 15~25 秒）。
        </p>
      </Card>
    );
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
      <div
        data-testid="plan-empty"
        className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_360px]"
      >
        <Card>
          <h3 className="text-sm font-semibold">作战计划</h3>
          <p className="mt-2 text-xs text-text-sec">
            {state.message}。生成后会得到三段内容：
            <br />① 今日复盘（昨日预案兑现了没有）② 明日市场预期（四维度规则推断）③ 明日逐票操作预案（什么价位做什么）。
          </p>
          <Button className="mt-3" size="sm" onClick={() => void generate()}>
            生成今日计划
          </Button>

          {/* 空态不留大片虚空:把「明天要看哪些票」摆出来 */}
          <div className="mt-4 border-t border-border-def pt-3">
            <div className="text-[11px] text-text-ter">
              目标股票池（持仓 ∪ ★关注）· 共 {scope.length} 只
            </div>
            {scope.length === 0 ? (
              <p className="mt-1.5 text-[11px] text-text-sec">
                还没有持仓也没有★关注票 —— 先在「盯盘台」加自选或建一笔持仓,作战计划才有对象。
              </p>
            ) : (
              <ul className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
                {scope.map((s) => (
                  <li key={s.stockCode} className="truncate py-0.5 text-[11px] text-text-pri">
                    {s.stockName ?? s.stockCode}
                    <span className="ml-1 font-mono text-text-ter">{s.stockCode}</span>
                    {s.inPosition && <span className="ml-1 text-text-sec">持仓</span>}
                    {s.isFavorite && <span className="ml-1 text-text-sec">★</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* 空态不留大片虚空:把三段内容各自「会写什么」讲清楚,而不是只留一句提示 */}
          <div className="mt-4 border-t border-border-def pt-3">
            <div className="text-[11px] text-text-ter">生成后你会看到什么</div>
            <ul className="mt-2 space-y-2">
              {THREE_SECTIONS.map((s) => (
                <li key={s.no} className="text-[11px] leading-relaxed">
                  <span className="font-semibold text-text-pri">
                    {s.no} {s.title}
                  </span>
                  <span className="text-text-sec"> —— {s.body}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* 空态不留大片虚空:说明复盘闭环从哪一天开始生效 */}
          <div className="mt-4 border-t border-border-def pt-3">
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
          <div className="mt-4 border-t border-border-def pt-3">
            <div className="text-[11px] text-text-ter">怎么用</div>
            <ul className="mt-1.5 space-y-1">
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
            <p className="mt-2 text-xs text-text-sec">
              生成时会按量能、涨跌家数、均线位置、板块资金四个维度做规则推断,并给出上证关键位 ——
              只写「倾向」,不预测涨跌。
            </p>
          </Card>
          <Card>
            <h3 className="text-sm font-semibold">明日逐票操作预案</h3>
            <p className="mt-2 text-xs text-text-sec">
              每条预案都会写死:什么价位、什么条件、做什么动作、依据是什么、什么情况下作废。
            </p>
          </Card>
          <Card>
            <h3 className="text-sm font-semibold">今日复盘</h3>
            <p className="mt-2 text-xs text-text-sec">
              拿昨天的每条预案对照今天的成交与行情:执行了记「已执行」,价位偏离超 3% 会写明
              成交价与触发价;当天没碰到价位的记「未触发」—— 不评价对错。
            </p>
          </Card>
        </div>
      </div>
    );
  }

  const { plan } = state;
  const scopeText = plan.meta?.scopeCount
    ? `覆盖 ${plan.meta.scopeCount} 只（持仓 + ★关注）`
    : '';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">作战计划</h2>
          <p className="mt-0.5 text-[11px] text-text-ter">
            {plan.planDate} · {scopeText}
            {plan.meta?.targetDateEstimated && plan.targetDate
              ? ` · 明日按工作日推算为 ${plan.targetDate}`
              : ''}
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => void generate()}>
          重新生成
        </Button>
      </div>

      {plan.meta?.degraded && (plan.meta.degradedReason ?? []).length > 0 && (
        <div className="rounded border border-warn/40 bg-warn-bg px-3 py-2 text-[11px] text-warn">
          部分数据缺失（已如实标注，未用假数据填补）：
          {plan.meta.degradedReason.join('；')}
        </div>
      )}

      {/* 窄屏(单栏)顺序:预期 → 预案 → 复盘;宽屏:左栏预案,右栏预期 + 复盘
          ⚠️ 断点用 lg(1024),不用 xl(1280) —— spec §5.2 铁律「两栏保持到 1024px」

          ⚠️ **右栏必须是一个 grid 子元素**(2026-10-22 收口修复):
          原来「预期」在 (col2,row1)、「复盘」在 (col2,row2),而第 2 行的顶边 =
          左栏 34 条预案的底边(5054px) → 复盘卡被推到 y≈5249,右栏中间约 4800px 全空。
          现在把两者包进**同一个** grid 子元素(内部 flex-col 纵向堆叠),
          窄屏用 `display: contents` 让包装容器「透明」成两个独立 grid item,
          窄屏顺序(预期 → 预案 → 复盘)因此不变。 */}
      <div
        data-testid="plan-grid"
        className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start xl:grid-cols-[minmax(0,1fr)_360px]"
      >
        {/* 左栏:明日逐票操作预案(34 条的主体,宽度不能被压) */}
        <div className="order-2 lg:order-1 lg:col-start-1 lg:row-start-1">
          <PlanItemList items={plan.items ?? []} targetDate={plan.targetDate ?? null} />
        </div>
        {/* 右栏:明日市场预期 + 今日复盘(紧邻堆叠;sticky 让它在左栏长列表滚动时始终可见) */}
        <div className="contents lg:sticky lg:top-4 lg:col-start-2 lg:row-start-1 lg:flex lg:flex-col lg:gap-4">
          <div className="order-1 lg:order-none">
            <OutlookCard outlook={plan.outlook} />
          </div>
          <div className="order-3 lg:order-none">
            <ReviewCard review={plan.review ?? null} />
          </div>
        </div>
      </div>
    </div>
  );
}
