'use client';

import { useCallback, useEffect, useState } from 'react';

import { ReplayCard } from '@/components/positions/ReplayCard';
import { TransactionForm } from '@/components/transaction/TransactionForm';
import { TransactionTable } from '@/components/transaction/TransactionTable';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { apiGet } from '@/lib/api';
import { refreshPositions } from '@/components/positions/PositionsSection';
import type { ReplaySummaries, ReplayWindow } from '@/lib/types';
import { useUIStore } from '@/stores/useUIStore';

/**
 * 持仓 Tab - 流水子视图(v2.3)
 *
 * 布局(顶 → 底):
 * 1. 顶部:股票名 + 代码 + 录入流水按钮(展开表单)
 * 2. 中部:一键复盘卡片(ReplayCard)
 * 3. 底部:该股票流水列表(按 stockCode 过滤)
 */
export function StockFlowTab({ stockCode, stockName }: { stockCode: string; stockName: string | null }) {
  const showToast = useUIStore((s) => s.showToast);
  const [showForm, setShowForm] = useState(false);
  const [summaries, setSummaries] = useState<ReplaySummaries | null>(null);
  const [txRefreshKey, setTxRefreshKey] = useState(0);

  // 加载 6 窗口最新复盘(初始化用)
  const loadSummaries = useCallback(async () => {
    try {
      const r = await apiGet<ReplaySummaries>(
        `/diagnose/stock/${encodeURIComponent(stockCode)}/summaries`,
      );
      setSummaries(r);
    } catch {
      /* 失败忽略,允许未复盘状态 */
    }
  }, [stockCode]);

  useEffect(() => {
    void loadSummaries();
    setShowForm(false);
  }, [loadSummaries]);

  const onTxSuccess = () => {
    showToast({ type: 'success', message: '流水已录入,持仓已同步' });
    setShowForm(false);
    setTxRefreshKey((k) => k + 1);
    refreshPositions();
    void loadSummaries(); // 新流水 → 复盘可能失效,重拉
  };

  // 默认 1 日 的最新复盘
  const initial = summaries?.windows?.[('1d' as ReplayWindow)] ?? null;

  return (
    <div className="space-y-4">
      {/* 顶部:股票信息 + 录入按钮 */}
      <Card padding="md" className="flex items-center justify-between">
        <div>
          <div className="font-semibold">
            {stockName ?? stockCode}
            <span className="text-text-ter text-sm ml-2 font-mono">
              {stockCode}
            </span>
          </div>
          <div className="text-xs text-text-ter mt-0.5">
            单只股票的流水 + 复盘视图
          </div>
        </div>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => setShowForm((v) => !v)}
        >
          {showForm ? '收起表单' : '+ 录入流水'}
        </Button>
      </Card>

      {showForm && (
        <Card padding="md">
          <TransactionForm
            initialStockCode={stockCode}
            onCancel={() => setShowForm(false)}
            onSuccess={onTxSuccess}
          />
        </Card>
      )}

      {/* 复盘卡片 */}
      <ReplayCard stockCode={stockCode} initial={initial} />

      {/* 流水列表 */}
      <Card padding="md">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold">流水列表</h3>
          <span className="text-xs text-text-ter">
            {summaries?.windows?.[('1d' as ReplayWindow)]?.summarySnapshot?.txCount != null
              ? `窗口内 ${summaries.windows['1d']!.summarySnapshot!.txCount} 笔`
              : ''}
          </span>
        </div>
        <TransactionTable refreshKey={txRefreshKey} stockCode={stockCode} />
      </Card>
    </div>
  );
}