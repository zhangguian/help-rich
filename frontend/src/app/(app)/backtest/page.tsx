'use client';

import { PageShell } from '@/components/shell/PageShell';
import { BacktestPanel } from '@/components/backtest/BacktestPanel';

/** /backtest — 策略回测 */
export default function BacktestPage() {
  return (
    <PageShell
      title="策略回测"
      subtitle="用历史选股信号验证策略,按 A 股真实规则与费率模拟"
      icon="📊"
      backHref="/screener"
      backLabel="返回选股"
    >
      <div className="max-w-4xl">
        <BacktestPanel />
      </div>
    </PageShell>
  );
}
