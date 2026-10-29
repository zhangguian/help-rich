import { PageShell } from '@/components/shell/PageShell';
import { PlanPanel } from '@/components/plan/PlanPanel';

/**
 * /plan · 每日作战计划(作战计划 v2)
 *
 * 三栏:左 = 股票锚点栏 + 今日复盘,中 = 逐票作战计划,右 = 明日市场预期。
 * 覆盖范围 = 持仓 ∪ ★关注(各自完整覆盖) + 沪深全市场主板滚动池(5 只),
 * 滚动池带记忆:达到预期就留,连续 3 天未达预期就剔除、由新股票补位。
 */
export default function PlanPage() {
  return (
    <PageShell
      title="作战计划"
      subtitle="持仓 ∪ ★关注 + 沪深全市场主板滚动池(5 只,带记忆):今天盯哪些票、每只票要做什么、昨天盯的结果"
      icon="🗓"
      wide
    >
      <PlanPanel />
    </PageShell>
  );
}
