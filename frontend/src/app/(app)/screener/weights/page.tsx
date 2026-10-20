'use client';

import { PageShell } from '@/components/shell/PageShell';
import { WeightsPanel } from '@/components/screener/WeightsPanel';

/** /screener/weights — 选股权重可调 */
export default function WeightsPage() {
  return (
    <PageShell
      title="选股权重"
      subtitle="调整各因子满分后保存;建议用「回测」验证敏感度再长期使用"
      icon="⚖️"
      backHref="/screener"
      backLabel="返回选股"
    >
      <div className="max-w-2xl">
        <WeightsPanel />
      </div>
    </PageShell>
  );
}
