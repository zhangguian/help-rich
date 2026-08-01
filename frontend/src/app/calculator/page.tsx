import { CalculatorPanel } from '@/components/calculator/CalculatorPanel';

/**
 * 成本计算器页(/calculator,P3.3 实施)
 *
 * MVP 版:仅 CalculatorPanel + 简单标题
 * P3.5 后加股票选择联想 + 当前价实时拉取
 */
export default function CalculatorPage() {
  return (
    <main className="min-h-screen p-8 max-w-6xl mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">交易成本计算器</h1>
        <p className="text-text-sec text-sm mt-1">
          输入股数与价格,实时计算新成本与 21 档盈亏表(MVP v0.1.0)
        </p>
      </header>

      <CalculatorPanel />
    </main>
  );
}