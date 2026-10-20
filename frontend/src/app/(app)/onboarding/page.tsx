'use client';

import { PageShell } from '@/components/shell/PageShell';
import { OnboardingPanel } from '@/components/onboarding/OnboardingPanel';

/** /onboarding — 引导中心 */
export default function OnboardingPage() {
  return (
    <PageShell
      title="开始使用"
      subtitle="按顺序完成这些配置,工具才能给出有意义的结果"
      icon="🚀"
    >
      <div className="max-w-2xl">
        <OnboardingPanel />
      </div>
    </PageShell>
  );
}
