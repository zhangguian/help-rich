'use client';

import { PageShell } from '@/components/shell/PageShell';
import { AccountsPanel } from '@/components/accounts/AccountsPanel';

/** /accounts — 多账户管理 */
export default function AccountsPage() {
  return (
    <PageShell
      title="投资账户"
      subtitle="多个券商账户分开统计,盈亏才不会算混"
      icon="🏦"
    >
      <div className="max-w-3xl">
        <AccountsPanel />
      </div>
    </PageShell>
  );
}
