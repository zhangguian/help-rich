'use client';

import { useState } from 'react';

import Link from 'next/link';

import { CalculatorPanel } from '@/components/calculator/CalculatorPanel';
import { HoldingsHealthPanel } from '@/components/holdings-health/HoldingsHealthPanel';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { LiquidModal } from '@/components/ui/LiquidModal';

/**
 * 历史工具卡(设置页)
 *
 * 计算器 / 持仓健康改为弹窗展示,其余工具仍跳转独立路由页。
 */
export function HistoryToolsCard() {
  const [showCalculator, setShowCalculator] = useState(false);
  const [showHealth, setShowHealth] = useState(false);

  return (
    <Card padding="md" className="space-y-3">
      <div>
        <div className="font-semibold">🕰 历史工具</div>
        <div className="text-xs text-text-ter mt-1">
          记账 / 报表向功能已从工作台撤出,如需使用请从下方进入。
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Link href="/transactions">
          <Button variant="secondary" className="w-full">
            📋 流水
          </Button>
        </Link>
        <Button
          variant="secondary"
          className="w-full"
          onClick={() => setShowCalculator(true)}
        >
          🧮 计算器
        </Button>
        <Link href="/annual-report/2025">
          <Button variant="secondary" className="w-full">
            📅 年账单
          </Button>
        </Link>
        <Link href="/risk-report">
          <Button variant="secondary" className="w-full">
            ⚠️ 风险报告
          </Button>
        </Link>
        <Link href="/rebalance">
          <Button variant="secondary" className="w-full">
            ⚖️ 调仓建议
          </Button>
        </Link>
        <Link href="/provider-stats">
          <Button variant="secondary" className="w-full">
            📊 Provider 占比
          </Button>
        </Link>
        <Button
          variant="secondary"
          className="w-full"
          onClick={() => setShowHealth(true)}
        >
          🩺 持仓健康
        </Button>
        <Link href="/sector-fund-flow">
          <Button variant="secondary" className="w-full">
            🗂 板块资金流
          </Button>
        </Link>
      </div>

      <LiquidModal
        open={showCalculator}
        onClose={() => setShowCalculator(false)}
        title="🧮 计算器"
        size="xl"
      >
        <CalculatorPanel />
      </LiquidModal>

      <LiquidModal
        open={showHealth}
        onClose={() => setShowHealth(false)}
        title="🩺 持仓体检"
        size="lg"
      >
        <HoldingsHealthPanel />
      </LiquidModal>
    </Card>
  );
}
