import { TReminderPanel } from '@/components/treminder/TReminderPanel';
import { PageShell } from '@/components/shell/PageShell';

/**
 * 补T提醒 — /t-reminders
 *
 * 做T挂单清单(反T待接回 + 正T待卖出,各带三档建议价与一键录入),
 * 到价提醒由后端自动对齐(反T ≤ / 正T ≥),挂单消失自动停用。
 * 左栏第一位的「🔁 补T提醒」清单指向本页。
 */
export default function TRemindersPage() {
  return (
    <PageShell
      title="补T提醒"
      subtitle="还没配上的做T单 —— 反T卖出了要接回,正T买进了要卖出"
      icon="🔁"
      backHref="/positions"
      backLabel="返回持仓"
      wide
    >
      <TReminderPanel />
    </PageShell>
  );
}
