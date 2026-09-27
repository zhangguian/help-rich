import { NavRail } from './NavRail';

/**
 * 应用外壳(v0.7 Dark Terminal)
 *
 * 持久左侧导航 + 右侧内容区。此前所有页面各自孤立、只有「← 返回首页」,
 * 本外壳让任意页面可直达任意模块。
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-canvas">
      <NavRail />
      <main className="flex-1 min-w-0 overflow-x-hidden">{children}</main>
    </div>
  );
}
