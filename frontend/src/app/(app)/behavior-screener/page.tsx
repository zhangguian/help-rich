'use client';

/**
 * /behavior-screener 独立路由 — 外层居中容器,适合大屏直接访问
 *
 * 找股:按 K 线行为信号(主力异动/低吸/锁仓/高抛)筛选全市场。
 * 与 `/screener`(选股 · 因子打分)口径不同,页内已写清区别。
 */
import { BehaviorScreenerPanel } from '@/components/screener/BehaviorScreenerPanel';

export default function BehaviorScreenerPage() {
  return (
    <div className="p-8 max-w-5xl mx-auto">
      <BehaviorScreenerPanel />
    </div>
  );
}
