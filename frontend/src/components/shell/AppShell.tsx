'use client';

import AssistantBall from '@/components/assistant/AssistantBall';
import AssistantDialog from '@/components/assistant/AssistantDialog';
import { AssistantProvider } from '@/components/assistant/AssistantProvider';
import { PriceAlertPopup } from '@/components/alert/PriceAlertPopup';
import { usePriceAlertStream } from '@/hooks/usePriceAlertStream';
import { NavRail } from './NavRail';

/**
 * 应用外壳(v0.8 Trading Desk)
 *
 * 持久左侧导航 + 右侧内容区。
 *
 * **v0.8 改动**:容器从 `min-h-screen`(整页滚动)改为 `h-screen` + 内部滚动。
 * 交易台首页需要「内容铺满视口」的满屏工作台(见 docs/design/trading-desk-v2.md),
 * 若外层仍随内容无限增高,首页的 `h-full` 就没有确定高度、虚空问题会原样复现。
 * 其它页面行为不变 —— 它们的内容超过视口时由 main 容器内部滚动。
 *
 * **阶段 10 改动**:挂上**全局 AI 助手**(右下角悬浮球 + 展开对话框)。
 * 放在 AppShell 是因为助手要**全站可见** —— 任何页面都能唤起它;
 * Provider 也在这里,所以助手拿得到盯盘页报上来的「当前选中的票」。
 *
 * **到价提醒弹窗**:同样挂全站 —— 提醒在哪一页触发都要看得见。
 * Windows 托盘气泡在部分 Win11 上不渲染,应用内弹窗是唯一的可靠兜底。
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  usePriceAlertStream();

  return (
    <AssistantProvider>
      <div className="flex h-screen overflow-hidden bg-canvas">
        <NavRail />
        <main className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden">{children}</main>
        <AssistantBall />
        <AssistantDialog />
        <PriceAlertPopup />
      </div>
    </AssistantProvider>
  );
}
