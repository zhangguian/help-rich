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
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      <NavRail />
      <main className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden">{children}</main>
    </div>
  );
}
