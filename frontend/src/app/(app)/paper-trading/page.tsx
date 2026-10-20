'use client';

import { PageShell } from '@/components/shell/PageShell';
import { PaperTradingPanel } from '@/components/paper/PaperTradingPanel';

/** /paper-trading — 模拟盘 */
export default function PaperTradingPage() {
  return (
    <PageShell
      title="模拟盘"
      subtitle="用真实行情练手,不花真钱。与真实持仓完全隔离"
      icon="🎮"
    >
      <div className="max-w-4xl">
        <PaperTradingPanel />
      </div>
    </PageShell>
  );
}
