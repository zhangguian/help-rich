import { PageShell } from '@/components/shell/PageShell';
import { PlanPanel } from '@/components/plan/PlanPanel';

/** /plan · 每日作战计划(今日复盘 + 明日市场预期 + 明日逐票操作预案) */
export default function PlanPage() {
  return (
    <PageShell
      title="作战计划"
      subtitle="今日复盘 + 明日市场预期 + 明日逐票操作预案:明天什么价位做什么,写在这里"
      icon="🗓"
    >
      <PlanPanel />
    </PageShell>
  );
}
