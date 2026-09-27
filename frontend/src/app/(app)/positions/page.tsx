'use client';

import { PositionsSection } from '@/components/positions/PositionsSection';
import { PageShell } from '@/components/shell/PageShell';
import { Card } from '@/components/ui/Card';

/**
 * 持仓 — /positions
 *
 * 由原首页「持仓」tab 抽出。
 *
 * 说明:原 positionView 的 3 个子视图(流水 / 持仓表)都依赖首页的 activeCode
 * (需先在盯盘列表点选一只股票),与本页的独立数据源不兼容,因此不做假段控。
 * 逐股流水与复盘由盯盘页的选中态 + /replay-history?code= + /stock/[code] 承载。
 */
export default function PositionsPage() {
  return (
    <PageShell title="💼 持仓" subtitle="持仓明细 · 一键清仓 · 止损设置">
      <Card padding="md">
        <PositionsSection />
      </Card>
    </PageShell>
  );
}
