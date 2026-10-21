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

export function PlanPanel() {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [scope, setScope] = useState<ScopeRow[]>([]);

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
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_360px]">
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
              <ul className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-3">
                {scope.map((s) => (
                  <li key={s.stockCode} className="truncate text-[11px] text-text-pri">
                    {s.stockName ?? s.stockCode}
                    <span className="ml-1 font-mono text-text-ter">{s.stockCode}</span>
                    {s.inPosition && <span className="ml-1 text-text-sec">持仓</span>}
                    {s.isFavorite && <span className="ml-1 text-text-sec">★</span>}
                  </li>
                ))}
              </ul>
            )}
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
          ⚠️ 断点用 lg(1024),不用 xl(1280) —— spec §5.2 铁律「两栏保持到 1024px」 */}
      <div
        data-testid="plan-grid"
        className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_360px]"
      >
        <div className="order-2 lg:order-1 lg:col-start-1 lg:row-start-1">
          <PlanItemList items={plan.items ?? []} targetDate={plan.targetDate ?? null} />
        </div>
        <div className="order-1 lg:order-2 lg:col-start-2 lg:row-start-1">
          <OutlookCard outlook={plan.outlook} />
        </div>
        <div className="order-3 lg:col-start-2 lg:row-start-2">
          <ReviewCard review={plan.review ?? null} />
        </div>
      </div>
    </div>
  );
}
