'use client';

import { PageShell } from '@/components/shell/PageShell';
import { PriceAlertEditor } from '@/components/alert/PriceAlertEditor';

/** /price-alerts — 价格提醒 */
export default function PriceAlertsPage() {
  return (
    <PageShell
      title="价格提醒"
      subtitle="到价自动推送到手机,不用一直盯盘"
      icon="🔔"
    >
      <div className="max-w-3xl">
        <PriceAlertEditor />
      </div>
    </PageShell>
  );
}
