'use client';

import { useState } from 'react';

import { PositionsSection } from '@/components/positions/PositionsSection';
import { PageShell } from '@/components/shell/PageShell';
import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { Card } from '@/components/ui/Card';

type View = 'kline' | 'positions' | 'risk';

const VIEWS = [
  { value: 'kline' as const, label: '📈 持仓明细' },
  { value: 'positions' as const, label: '🧾 汇总表' },
  { value: 'risk' as const, label: '⚠️ 风险' },
];

/**
 * 持仓 — /positions
 *
 * 由原首页「持仓」tab 抽出(该 tab 依赖首页局部 state,无法独立成路由)。
 * 子视图改用共享 SegmentedControl。
 *
 * 说明:原 positionView 的「流水」子视图依赖首页的 activeCode(需在盯盘列表点选股票),
 * 与本页独立数据源不兼容,故改为「持仓明细 / 汇总表 / 风险」三视图;
 * 逐股流水与复盘改由 /replay-history?code= 与 /stock/[code] 承载。
 */
export default function PositionsPage() {
  const [view, setView] = useState<View>('kline');

  return (
    <PageShell title="💼 持仓" subtitle="持仓明细 / 汇总表 / 风险敞口">
      <div className="flex items-center gap-2">
        <SegmentedControl options={VIEWS} value={view} onChange={setView} size="md" />
      </div>

      {view === 'kline' && <PositionsSection />}

      {view === 'positions' && (
        <Card padding="md" className="min-h-[320px] flex items-center justify-center">
          <p className="text-sm text-text-ter">
            汇总表随「持仓明细」中的股票选择联动显示
          </p>
        </Card>
      )}

      {view === 'risk' && (
        <Card padding="md" className="min-h-[320px] flex items-center justify-center">
          <p className="text-sm text-text-ter">
            风险敞口详见
            <a href="/risk-report" className="text-accent hover:underline mx-1">
              风险报告
            </a>
            与
            <a href="/holdings-health" className="text-accent hover:underline mx-1">
              持仓体检
            </a>
          </p>
        </Card>
      )}
    </PageShell>
  );
}
