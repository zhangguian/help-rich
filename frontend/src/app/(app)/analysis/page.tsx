'use client';

import { PageShell } from '@/components/shell/PageShell';
import { MultiAgentPanel } from '@/components/analysis/MultiAgentPanel';

/** /analysis — 多智能体深度分析 */
export default function AnalysisPage() {
  return (
    <PageShell
      title="深度分析"
      subtitle="多智能体辩论:4 位分析师 → 多空对辩 → 风控审查 → 投资经理裁决"
      icon="🤖"
    >
      <div className="max-w-4xl">
        <MultiAgentPanel />
      </div>
    </PageShell>
  );
}
