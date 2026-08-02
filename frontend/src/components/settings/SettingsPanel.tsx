import { Card } from '@/components/ui/Card';
import { ExportImportCard } from '@/components/settings/ExportImportCard';
import { HistoryToolsCard } from '@/components/settings/HistoryToolsCard';
import { LlmKeysCard } from '@/components/settings/LlmKeysCard';
import { LlmProviderCard } from '@/components/settings/LlmProviderCard';
import { ScreenshotPanel } from '@/components/screenshot/ScreenshotPanel';

/**
 * 设置面板(roadmap §4.0 工作台四区 — 设置 tab 内容)
 *
 * 6 个区块(自上而下):
 * 1. 数据备份/导入(ExportImportCard)
 * 2. LLM Provider(LlmProviderCard)
 * 3. LLM Keys(LlmKeysCard)
 * 4. 截图识别(ScreenshotPanel)
 * 5. 历史工具(HistoryToolsCard)— 包含二级跳转路由 / 弹窗
 * 6. 关于(内联 Card)
 *
 * 设计要点:
 * - 复用 settings/page.tsx 原有 6 个区块内容
 * - 不带外层 <main> 容器(让父级 page.tsx 主工作台容器控制布局)
 * - 容器自带 w-[800px] + mx-auto + py-4,适配主工作台中间区宽度
 * - 子模块客户端状态(export/import progress、screenshot modal)各自独立管理
 */
export function SettingsPanel() {
  return (
    <div className=" w-[800px] mx-auto  h-full overflow-y-auto px-6 py-6 space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-bold">设置</h2>
        <p className="text-text-sec text-sm">
          数据备份 · LLM Provider · API Key · 截图识别 · 历史工具 · 关于
        </p>
      </header>

      <div className=" space-y-6">
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
      </div>
    </div>
  );
}