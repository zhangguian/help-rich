import Link from 'next/link';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { decimalFormat } from '@/lib/decimalFormat';
import type { Position, PositionListResponse } from '@/lib/types';

import { apiGet } from '@/lib/api';

/**
 * 首页持仓概览(P2.5 实施,frontend-arch §10.1 / ui-ux §4.1)
 *
 * 顶部:总览(总市值 / 总成本 / 总浮盈)
 * 中部:持仓列表(无持仓 → 空状态)
 * 底部:快捷入口(录入流水 / 计算器)
 *
 * 当前价 / 今日盈亏 / 浮盈(依赖行情接口,P3.5 实施)
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
  // MVP 阶段无 current_price,floating_pnl 暂用 0
  const floatingPnl = 0;

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
        </div>
      </header>

      {/* 总览 */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1">总成本</div>
          <div className="text-2xl font-mono font-semibold">
            ¥{decimalFormat(totalCost.toFixed(2))}
          </div>
        </Card>
        <Card padding="md">
          <div className="text-text-sec text-sm mb-1">总浮盈(MVP 暂为 0)</div>
          <div className="text-2xl font-mono font-semibold text-text-ter">
            ¥{decimalFormat(floatingPnl.toFixed(2))}
          </div>
          <div className="text-xs text-text-ter mt-1">P3.5 接入行情后填充</div>
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
        <div className="space-y-3">
          {positions.map((p) => (
            <Card key={p.stockCode} padding="md">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-semibold">
                    {p.stockName ?? p.stockCode}
                    <span className="text-text-ter text-sm ml-2 font-mono">
                      {p.stockCode}
                    </span>
                  </div>
                  <div className="text-sm text-text-sec mt-1">
                    持仓 <span className="font-mono">{p.shares}</span> 股 ·
                    加权成本 <span className="font-mono">¥{p.avgCost}</span> ·
                    总成本 <span className="font-mono">¥{decimalFormat(p.totalCost)}</span>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xs text-text-ter">已实现盈亏</div>
                  <div
                    className={`text-lg font-mono font-semibold ${
                      Number(p.realizedPnl) >= 0 ? 'text-down' : 'text-up'
                    }`}
                  >
                    ¥{decimalFormat(p.realizedPnl)}
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      <footer className="mt-12 text-center text-text-ter text-xs">
        ⚠ 投资有风险,本工具所有输出仅供参考,不构成投资建议。
      </footer>
    </main>
  );
}