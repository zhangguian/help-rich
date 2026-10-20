'use client';

import { PageShell } from '@/components/shell/PageShell';
import { BriefPanel } from '@/components/analysis/BriefPanel';

/** /brief — 盘前简报 / 盘中速览 */
export default function BriefPage() {
  return (
    <PageShell
      title="盘前简报"
      subtitle="三段式 Agent:盘前 08:30 自动生成,盘中 11:30 / 14:50 速览,推送到手机"
      icon="📰"
    >
      <div className="max-w-3xl">
        <BriefPanel />
      </div>
    </PageShell>
  );
}
