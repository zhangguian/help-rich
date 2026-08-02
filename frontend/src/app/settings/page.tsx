import Link from 'next/link';

import { ExportImportCard } from '@/components/settings/ExportImportCard';
import { HistoryToolsCard } from '@/components/settings/HistoryToolsCard';
import { LlmKeysCard } from '@/components/settings/LlmKeysCard';
import { LlmProviderCard } from '@/components/settings/LlmProviderCard';
import { ScreenshotPanel } from '@/components/screenshot/ScreenshotPanel';
import { Card } from '@/components/ui/Card';

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

  <HistoryToolsCard />


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