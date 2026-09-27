import AppShell from '@/components/shell/AppShell';

/**
 * 路由组外壳 — 承载持久左侧导航。
 * 路由组不改变 URL: /screener 仍是 /screener。
 */
export default function AppGroupLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
