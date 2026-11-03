'use client';

import { useState } from 'react';

import { TransactionForm } from '@/components/transaction/TransactionForm';
import { TransactionTable } from '@/components/transaction/TransactionTable';
import { Button } from '@/components/ui/Button';
import { LiquidModal } from '@/components/ui/LiquidModal';
import { useUIStore } from '@/stores/useUIStore';
import { useTReminderStore } from '@/stores/useTReminderStore';

import { refreshPositions } from './PositionsSection';

/**
 * 持仓侧「录入流水」弹窗(持仓卡片 → 📝 录入流水)
 *
 * 内容:
 * 1. 上半:录入表单(代码只读、带交易时间节点)
 * 2. 下半:该股流水表(带评分列 + 评分详情)
 *
 * 录完一笔 → 持仓同步(重放成本链)→ 持仓卡片数字刷新,
 * 新那笔的分数由 SSE 推来(评分徽章先 loading 后跳分)。
 */
export function PositionTransactionModal({
  open,
  onClose,
  stockCode,
  stockName,
}: {
  open: boolean;
  onClose: () => void;
  stockCode: string;
  stockName: string | null;
}) {
  const showToast = useUIStore((s) => s.showToast);
  // 弹窗本来就是从「📝 录入流水」点进来的 → 表单默认展开
  const [showForm, setShowForm] = useState(true);
  const [txRefreshKey, setTxRefreshKey] = useState(0);

  const onTxSuccess = () => {
    showToast({ type: 'success', message: '流水已录入,持仓已同步' });
    setShowForm(false);
    setTxRefreshKey((k) => k + 1);
    refreshPositions();
    // 卖出/买回会改变「待接回清单」——左栏第一位的补T提醒同步刷新
    void useTReminderStore.getState().refresh();
  };

  return (
    <LiquidModal
      open={open}
      onClose={onClose}
      title={`${stockName ?? stockCode} ${stockCode} · 流水`}
      size="2xl"
    >
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="text-xs text-text-ter">
            录入这只股票的交易流水,每笔会自动打分(6 维度 / 120 分)
          </div>
          <Button size="sm" variant="secondary" onClick={() => setShowForm((v) => !v)}>
            {showForm ? '收起表单' : '+ 录入流水'}
          </Button>
        </div>

        {showForm && (
          <div className="border border-border-def rounded-sm p-4 bg-bg-surface">
            <TransactionForm
              initialStockCode={stockCode}
              onCancel={() => setShowForm(false)}
              onSuccess={onTxSuccess}
            />
          </div>
        )}

        <div>
          <h3 className="text-sm font-semibold mb-2">流水列表</h3>
          <TransactionTable refreshKey={txRefreshKey} stockCode={stockCode} />
        </div>
      </div>
    </LiquidModal>
  );
}
