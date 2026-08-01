import Link from 'next/link';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ExportImportCard } from '@/components/settings/ExportImportCard';
import { LlmKeysCard } from '@/components/settings/LlmKeysCard';
import { LlmProviderCard } from '@/components/settings/LlmProviderCard';
import { ScreenshotPanel } from '@/components/screenshot/ScreenshotPanel';

/**
 * 设置页(P7.3 + P7.11 + P7.12 + P8.9)
 *
 * 区块:
 * - 数据备份/导入(P7.3)
 * - LLM Provider(P7.11)
 * - LLM Keys(P7.12)
 * - 截图识别(P8.9)
 * - 关于 + 跳转其他页面
 */
export default function SettingsPage() {
  return (
    <main className="min-h-screen p-8 max-w-3xl mx-auto space-y-6">
      <header>
        <Link href="/" className="text-sm text-text-sec hover:text-text-pri">
          ← 返回首页
        </Link>
        <h1 className="text-2xl font-bold mt-2">设置</h1>
        <p className="text-text-sec text-sm mt-1">
          数据备份 · LLM Provider · API Key · 截图识别 · 关于
        </p>
      </header>

      <ExportImportCard />

      <LlmProviderCard />

      <LlmKeysCard />

      <ScreenshotPanel />

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
          <Link href="/calculator">
            <Button variant="secondary" className="w-full">
              🧮 计算器
            </Button>
          </Link>
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
          <Link href="/holdings-health">
            <Button variant="secondary" className="w-full">
              🩺 持仓健康
            </Button>
          </Link>
          <Link href="/sector-fund-flow">
            <Button variant="secondary" className="w-full">
              🗂 板块资金流
            </Button>
          </Link>
        </div>
      </Card>

      <Card padding="md" className="space-y-2">
        <div className="font-semibold">📋 关于</div>
        <div className="text-sm text-text-sec">
          买股工具室 v0.4 — 小白股民买股看股辅助工具
        </div>
        <div className="text-xs text-text-ter mt-2">
          ⚠ 投资有风险,本工具所有输出仅供参考,不构成投资建议。
        </div>
      </Card>
    </main>
  );
}