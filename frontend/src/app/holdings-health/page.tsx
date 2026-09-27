import { HoldingsHealthPanel } from '@/components/holdings-health/HoldingsHealthPanel';

/**
 * 持仓体检 — /holdings-health
 *
 * 复用设置页 HistoryToolsCard 弹窗内同一组件(ADR/计划 U3:两处入口都保留),
 * 本页解决 PositionsSection 中指向该路由的断链。
 */
export default function HoldingsHealthPage() {
  return (
    <main className="min-h-screen p-8 max-w-5xl mx-auto space-y-6">
      <header>
        <a
          href="/"
          className="text-sm text-text-ter hover:text-accent"
        >
          ← 返回首页
        </a>
        <h1 className="text-2xl font-semibold text-text-pri mt-2">🩺 持仓体检</h1>
        <p className="text-sm text-text-sec mt-1">风险敞口 / 集中度 / 健康度评分</p>
      </header>

      <HoldingsHealthPanel />
    </main>
  );
}
