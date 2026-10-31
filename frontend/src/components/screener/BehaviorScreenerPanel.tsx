'use client';

import { useCallback, useEffect, useState } from 'react';

import Link from 'next/link';

import { apiPost } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { SkeletonState } from '@/components/ui/States';
import {
  fetchBehaviorLatest,
  fetchBehaviorPool,
  type BehaviorGroup,
  type BehaviorLatestResponse,
  type BehaviorPick,
  type BehaviorPoolResponse,
} from '@/lib/behaviorScreener';

/** 信号类型 → 徽章配色(与 K 线图标注颜色同源) */
const KIND_CLS: Record<BehaviorPick['kind'], string> = {
  main_force_move: 'text-warn border-warn/30 bg-warn/10',
  dip_buy: 'text-info border-info/30 bg-info/10',
  lock_position: 'text-text-sec border-border-def bg-bg-subtle',
  distribute: 'text-down border-down/30 bg-down/10',
};

/** 错误类型:区分 404(还没跑) vs 其他错误 */
type LoadError =
  | { code: 'no_data'; message: string }
  | { code: 'error'; message: string }
  | null;

const fmtPct = (v: number | null) =>
  v == null ? '-' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;

/**
 * 找股面板 — 按 K 线行为信号(主力异动/低吸/锁仓/高抛)筛选全市场
 *
 * ⚠️ 与「选股」页的口径区别(两者都在 NavRail「决策」组):
 * - 选股:因子打分(主力净流入/量比/动能/板块强度/事件热度)→ 综合 Top 20
 * - 找股:K 线行为信号命中 → 按信号类型分组
 *
 * 空态严格区分「还没跑」与「跑了但没命中」——不编数字。
 */
export function BehaviorScreenerPanel() {
  const [data, setData] = useState<BehaviorLatestResponse | null>(null);
  const [pool, setPool] = useState<BehaviorPoolResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<LoadError>(null);
  const [triggering, setTriggering] = useState(false);

  const loadLatest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [latest, poolInfo] = await Promise.all([
        fetchBehaviorLatest(),
        fetchBehaviorPool(),
      ]);
      setData(latest);
      setPool(poolInfo);
    } catch (e: any) {
      if (e?.response?.status === 404) {
        setError({
          code: 'no_data',
          message:
            '尚无找股记录。可点击下方按钮立即跑批(需后端开启 SCREENER_ALLOW_TRIGGER),或在盘后跑批后查看。',
        });
      } else {
        setError({ code: 'error', message: e?.message || '加载失败' });
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLatest();
  }, [loadLatest]);

  const handleTriggerNow = useCallback(async () => {
    setTriggering(true);
    try {
      // 全市场扫描较慢(拉快照 + 逐票算信号),延长超时
      await apiPost('/behavior-screener/trigger-now', undefined, { timeout: 300000 });
      await loadLatest();
    } catch (e: any) {
      if (e?.response?.status === 403) {
        setError({
          code: 'no_data',
          message:
            '立即跑批需要后端开启 `SCREENER_ALLOW_TRIGGER=1` 环境变量。请联系管理员启动后端时加上该变量,然后重试。',
        });
      } else {
        setError({
          code: 'error',
          message: e?.response?.data?.detail || e?.message || '跑批失败',
        });
      }
    } finally {
      setTriggering(false);
    }
  }, [loadLatest]);

  if (loading) {
    return <SkeletonState rows={6} />;
  }

  if (error) {
    if (error.code === 'no_data') {
      return (
        <Card className="p-6">
          <p className="text-orange-500 font-medium">🔍 尚无找股记录</p>
          <p className="text-text-sec mt-2 text-sm whitespace-pre-line">
            {error.message}
          </p>
          <div className="flex gap-2 mt-4">
            <Button
              variant="primary"
              size="sm"
              onClick={handleTriggerNow}
              loading={triggering}
              disabled={triggering}
            >
              ⚡ 立即跑批
            </Button>
            <Button variant="ghost" size="sm" onClick={loadLatest}>
              🔄 刷新
            </Button>
          </div>
        </Card>
      );
    }
    return (
      <Card className="p-6">
        <p className="text-red-500 font-medium">⚠ 加载失败</p>
        <p className="text-text-sec mt-2 text-sm">{error.message}</p>
        <Button variant="ghost" size="sm" onClick={loadLatest} className="mt-4">
          🔄 重试
        </Button>
      </Card>
    );
  }

  if (!data || !data.run) {
    return (
      <Card className="p-6">
        <p className="text-text-sec">尚无找股数据</p>
      </Card>
    );
  }

  const { run, groups, all } = data;
  const universe = run.poolSize;
  const filters = run.afterFiltersCount;
  const candidates = run.candidatesConsidered;
  const hits = all.length;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">🔍 找股 · K 线行为信号</h1>
          <p className="text-text-sec mt-1 text-sm">
            {run.runDate} · 按 K 线形态 + 主力资金流筛选全市场
            {run.elapsedSec != null && ` · 耗时 ${run.elapsedSec.toFixed(1)}s`}
          </p>
          {/* 口径说明:与「选股」页的区别,避免用户以为两页数据应一致 */}
          <p className="text-text-ter mt-1 text-xs">
            ⓘ 按 K 线行为信号筛选,与「选股」的因子打分口径不同 ——
            「选股」按主力净流入/量比等因子排 Top 20,本页按信号命中分组。
          </p>
          {run.note && (
            <p className="text-text-ter mt-1 text-xs">⚠ {run.note}</p>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={handleTriggerNow}
            loading={triggering}
            disabled={triggering}
          >
            ⚡ 立即跑批
          </Button>
          <Button variant="ghost" size="sm" onClick={loadLatest}>
            🔄 刷新
          </Button>
        </div>
      </div>

      {/* 口径条:如实披露各级真实数字 */}
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <Step label="全市场快照" value={universe} />
          <Arrow />
          <Step label="成交额达标" value={filters} />
          <Arrow />
          <Step label="逐票算信号" value={candidates} />
          <Arrow />
          <Step label="命中信号" value={hits} highlight />
        </div>
        {pool?.universe && (
          <p className="text-text-ter mt-2 text-xs">
            主板 {pool.universe.mainBoard} 只 · 非 ST {pool.universe.nonSt} 只 ·
            成交额 ≥ 1 亿后剩 {pool.universe.afterFilters} 只
          </p>
        )}
      </Card>

      {/* 分组:按信号类型 */}
      {groups.length === 0 ? (
        <Card className="p-6">
          <p className="text-text-sec">本次扫描没有命中任何行为信号。</p>
          <p className="text-text-ter mt-1 text-xs">
            信号基于当日可观测事实(资金流 + K 线形态),没命中就是没命中 ——
            不代表后续不会涨,也不代表会跌。
          </p>
        </Card>
      ) : (
        groups.map((g) => <GroupCard key={g.kind} group={g} />)
      )}

      <p className="text-text-ter/80 pb-2 text-[10.5px] leading-relaxed">
        信号只标注已发生的形态事实,不预测后续涨跌,也不构成买卖依据。
        历史数据仅供参考,不作为买卖依据。
      </p>
    </div>
  );
}

function Step({
  label,
  value,
  highlight,
}: {
  label: string;
  value: number;
  highlight?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-text-ter text-xs">{label}</span>
      <span
        className={
          highlight
            ? 'text-accent text-base font-semibold'
            : 'text-text-pri text-base font-semibold'
        }
      >
        {value}
      </span>
    </div>
  );
}

function Arrow() {
  return <span className="text-text-ter/60 text-xs">→</span>;
}

function GroupCard({ group }: { group: BehaviorGroup }) {
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <span
          className={`rounded-full border px-2 py-0.5 text-xs font-medium ${KIND_CLS[group.kind]}`}
        >
          {group.kindLabel}
        </span>
        <span className="text-text-ter text-xs">{group.count} 只命中</span>
      </div>
      <ul className="space-y-2">
        {group.picks.map((p) => (
          <li
            key={`${p.stockCode}-${p.kind}`}
            className="rounded-sm border border-border-def bg-bg-subtle px-3 py-2"
          >
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <Link
                href={`/stock/${encodeURIComponent(p.stockCode)}`}
                className="text-text-pri text-sm font-medium hover:text-accent"
              >
                {p.stockName || p.stockCode}
              </Link>
              <span className="text-text-ter text-xs">{p.stockCode}</span>
              <span className="text-text-ter text-xs">
                信号日 {p.signalDate}（{p.daysAgo} 天前）
              </span>
              {p.changePct != null && (
                <span
                  className={
                    p.changePct >= 0
                      ? 'text-up text-xs font-medium'
                      : 'text-down text-xs font-medium'
                  }
                >
                  {fmtPct(p.changePct)}
                </span>
              )}
              <span className="text-text-ter ml-auto text-xs">
                强度 {p.score.toFixed(1)}
              </span>
            </div>
            <p className="text-text-sec mt-1 text-xs leading-relaxed">
              {p.reason}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  );
}
