import Link from 'next/link';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { PositionsList } from '@/components/positions/PositionsList';
import { OnboardingHint } from '@/components/onboarding/OnboardingHint';
import { ScreenshotPanel } from '@/components/screenshot/ScreenshotPanel';
import { decimalFormat } from '@/lib/decimalFormat';
import type { Position, PositionListResponse } from '@/lib/types';

import { apiGet } from '@/lib/api';

/**
 * 首页持仓概览(P2.5 实施,P3.5.2 接入行情)
 *
 * 顶部:总览(总市值 / 总成本 / 总浮盈 + 今日盈亏)
 * 中部:持仓列表(每只含 今日盈亏 / 浮动盈亏 / 现价)
 * 底部:快捷入口(录入流水 / 计算器)
 *
 * 行情字段 currentPrice / todayPnl / floatingPnl:
 *   后端返回 null 时(行情源不可用)降级显示 "--"
 */
export default async function Home() {
  let positions: Position[] = [];
  let backendOk = false;

  try {
    const resp = await apiGet<PositionListResponse>('/positions');
    positions = resp.items;
    backendOk = true;
  } catch {
    backendOk = false;
  }

  const totalCost = positions.reduce((sum, p) => sum + Number(p.totalCost), 0);
  const floatingPnl = positions.reduce((sum, p) => sum + Number(p.floatingPnl ?? 0), 0);
  const todayPnl = positions.reduce((sum, p) => sum + Number(p.todayPnl ?? 0), 0);
  const hasQuotes = positions.some((p) => p.currentPrice !== null);

  const pnlClass = (v: number) => (v >= 0 ? 'text-up' : 'text-down');  return (
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
          <h1 className="text-3xl font-bold">盘后诊股室</h1>
          <p className="text-text-sec text-sm mt-1">
            个人股票 AI 诊断 Agent — MVP v0.1.0
          </p>
        </div>
        <div className="flex gap-2">
          <Link href="/transactions">
            <Button variant="secondary">📋 流水录入</Button>
          </Link>
          <Link href="/calculator">
            <Button>🧮 计算器</Button>
          </Link>
          <Link href="/settings">
            <Button variant="ghost">⚙ 设置</Button>
          </Link>
        </div>
      </header>

      {/* 总览(P3.5.2:4 宫格) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1">总成本</div>
          <div className="text-2xl font-mono font-semibold">
            ¥{decimalFormat(totalCost.toFixed(2))}
          </div>
        </Card>
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1">总浮盈</div>
          <div className={`text-2xl font-mono font-semibold ${pnlClass(floatingPnl)}`}>
            {hasQuotes ? `¥${decimalFormat(floatingPnl.toFixed(2))}` : '--'}
          </div>
          <div className="text-xs text-text-ter mt-1">
            {hasQuotes ? '现价 - 加权成本' : '行情暂不可用'}
          </div>
        </Card>
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1">今日盈亏</div>
          <div className={`text-2xl font-mono font-semibold ${pnlClass(todayPnl)}`}>
            {hasQuotes ? `¥${decimalFormat(todayPnl.toFixed(2))}` : '--'}
          </div>
          <div className="text-xs text-text-ter mt-1">
            {hasQuotes ? '现价 - 昨收' : '行情暂不可用'}
          </div>
        </Card>
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1">持仓数</div>
          <div className="text-2xl font-mono font-semibold">{positions.length}</div>
        </Card>
      </div>

      {/* 持仓列表 */}
      <h2 className="text-lg font-semibold mb-3">我的持仓</h2>
      {positions.length === 0 ? (
        <Card padding="lg">
          <div className="text-center py-8">
            <p className="text-text-ter mb-4">还没有持仓记录</p>
            <Link href="/transactions">
              <Button>+ 录入第一笔交易</Button>
            </Link>
          </div>
        </Card>
      ) : (
        <PositionsList positions={positions} />
      )}

      <section className="mt-8">
        <h2 className="text-lg font-semibold mb-3">截图识别</h2>
        <ScreenshotPanel />
      </section>

      <OnboardingHint />

      <footer className="mt-12 text-center text-text-ter text-xs">
        ⚠ 投资有风险,本工具所有输出仅供参考,不构成投资建议。
      </footer>
    </main>
  );
}
