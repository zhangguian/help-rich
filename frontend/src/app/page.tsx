import Link from 'next/link';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { NewsFeed } from '@/components/news/NewsFeed';
import { PositionsSection } from '@/components/positions/PositionsSection';
import { OnboardingHint } from '@/components/onboarding/OnboardingHint';
import { ReflectionCard } from '@/components/reflection/ReflectionCard';
import { ScreenshotPanel } from '@/components/screenshot/ScreenshotPanel';

import { apiGet } from '@/lib/api';
import type { PositionListResponse } from '@/lib/types';

/**
 * 首页持仓概览(P2.5 实施,P3.5.2 接入行情,v0.4.0 client 化)
 *
 * 顶部:总览(总市值 / 总成本 / 总浮盈 + 今日盈亏)
 * 中部:持仓列表(每只含 今日盈亏 / 浮动盈亏 / 现价 / 删除)+ 添加持仓
 * 底部:快捷入口(录入流水 / 计算器 / 持仓体检)
 *
 * 行情字段 currentPrice / todayPnl / floatingPnl:
 *   后端返回 null 时(行情源不可用)降级显示 "--"
 * 持仓导入(v0.4.0):截图识别粘贴持仓 JSON / 手动添加 → positions 主数据
 */
export default async function Home() {
  let backendOk = false;

  try {
    await apiGet<PositionListResponse>('/positions');
    backendOk = true;
  } catch {
    backendOk = false;
  }

  return (
    <main className="min-h-screen p-8 max-w-6xl mx-auto">
      {!backendOk && (
        <Card className="mb-6 border-warn">
          <p className="text-warn text-sm">
            ⚠ 后端未连接,请先启动 uvicorn(参考 docs/dev-log/runbook.md)
          </p>
        </Card>
      )}

      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">买股工具室</h1>
          <p className="text-text-sec text-sm mt-1">
            个人股票投资辅助工具 — MVP v0.1.0
          </p>
        </div>
        <div className="flex gap-2">
          <Link href="/transactions">
            <Button variant="secondary">📋 流水录入</Button>
          </Link>
          <Link href="/calculator">
            <Button>🧮 计算器</Button>
          </Link>
          <Link href={`/annual-report/${new Date().getFullYear() - 1}`}>
            <Button variant="secondary">📊 年账单</Button>
          </Link>
          <Link href="/risk-report">
            <Button variant="secondary">🛡 风险报告</Button>
          </Link>
          <Link href="/rebalance">
            <Button variant="secondary">🎯 调仓建议</Button>
          </Link>
          <Link href="/sector-fund-flow">
            <Button variant="secondary">💰 板块资金</Button>
          </Link>
          <Link href="/provider-stats">
            <Button variant="ghost">📊 Provider 占比</Button>
          </Link>
          <Link href="/settings">
            <Button variant="ghost">⚙ 设置</Button>
          </Link>
        </div>
      </header>

      <PositionsSection />

      <ReflectionCard />

      <section className="mt-8">
        <h2 className="text-lg font-semibold mb-3">截图识别</h2>
        <ScreenshotPanel />
      </section>

      <section className="mt-8">
        <NewsFeed />
      </section>

      <OnboardingHint />

      <footer className="mt-12 text-center text-text-ter text-xs">
        ⚠ 投资有风险,本工具所有输出仅供参考,不构成投资建议。
      </footer>
    </main>
  );
}
