import Link from 'next/link';

import { SettingsPanel } from '@/components/settings/SettingsPanel';

/**
 * 设置路由薄壳(roadmap §4.0 后保留)
 *
 * 主工作台已集成设置 tab(见 app/page.tsx);此路由仅作为深链直达入口
 * (如分享链接、外部分享、收藏夹等)。点击「返回首页」可回到工作台。
 */
export default function SettingsPage() {
  return (
    <main className="min-h-screen p-8 max-w-3xl mx-auto">
      <header className="mb-6">
        <Link href="/" className="text-sm text-text-sec hover:text-text-pri">
          ← 返回首页
        </Link>
      </header>
      <SettingsPanel />
    </main>
  );
}