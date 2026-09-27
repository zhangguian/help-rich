'use client';

import { ScreenerPanel } from '@/components/screener/ScreenerPanel';

/** /screener 独立路由 — 外层居中容器,适合大屏直接访问
 *  主页 tab 内嵌由 page.tsx 直接 import ScreenerPanel 渲染
 */
export default function ScreenerPage() {
  return (
    <div className="p-8 max-w-5xl mx-auto">
      <ScreenerPanel />
    </div>
  );
}