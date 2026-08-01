'use client';

import { useState } from 'react';

import { apiPost } from '@/lib/api';
import { useUIStore } from '@/stores/useUIStore';

import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';

/**
 * 截图预览 + 确认/重试(P8.7)
 *
 * - 表格展示识别结果(可逐行勾选)
 * - 列出股票代码 / 名称 / 关键字段
 * - 确认入库(POST /api/screenshot/{id}/confirm)
 * - 拒绝 / 重试
 */
export function ScreenshotPreview({
  recordId,
  screenshotType,
  items: initialItems,
  onRetake,
  onClose,
}: {
  recordId: number;
  screenshotType: string;
  items: Array<Record<string, unknown>>;
  onRetake: () => void;
  onClose: () => void;
}) {
  const showToast = useUIStore((s) => s.showToast);
  const [items, setItems] = useState(initialItems);
  const [busy, setBusy] = useState(false);

  const toggleRow = (idx: number) => {
    // 简化:整批确认,不提供逐行编辑(MVP)
  };

  const confirm = async () => {
    setBusy(true);
    try {
      await apiPost(`/screenshot/${recordId}/confirm`, {
        items,
        screenshotType,
      });
      showToast({ type: 'success', message: `已确认 ${items.length} 条入库` });
      onClose();
    } catch {
      showToast({ type: 'error', message: '确认失败,请重试' });
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    if (!window.confirm('确认取消此次识别?')) return;
    setBusy(true);
    try {
      await apiPost(`/screenshot/${recordId}/reject`);
      showToast({ type: 'info', message: '已取消' });
      onClose();
    } catch {
      showToast({ type: 'error', message: '取消失败' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card padding="lg" className="space-y-4">
      <header className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          预览识别结果
          <span className="ml-2 text-xs">
            <Badge variant={screenshotType === 'transactions' ? 'mid' : 'good'}>
              {screenshotType}
            </Badge>
          </span>
        </h2>
        <button onClick={onClose} className="text-text-ter hover:text-text-pri text-xl">×</button>
      </header>

      <div className="text-sm text-text-sec">
        共识别 <span className="font-mono font-semibold">{items.length}</span> 条记录,请核对后确认入库。
      </div>

      <div className="overflow-x-auto border border-border-def rounded-sm">
        <table className="w-full text-sm">
          <thead className="bg-bg-subtle text-text-sec">
            <tr>
              <th className="text-left px-3 py-2">代码</th>
              <th className="text-left px-3 py-2">名称</th>
              {screenshotType === 'transactions' && (
                <>
                  <th className="text-left px-3 py-2">方向</th>
                  <th className="text-right px-3 py-2">股数</th>
                  <th className="text-right px-3 py-2">价格</th>
                  <th className="text-left px-3 py-2">日期</th>
                </>
              )}
              {screenshotType === 'position' && (
                <>
                  <th className="text-right px-3 py-2">股数</th>
                  <th className="text-right px-3 py-2">成本</th>
                  <th className="text-right px-3 py-2">市值</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr
                key={i}
                className="border-t border-border-def hover:bg-bg-subtle cursor-pointer"
                onClick={() => toggleRow(i)}
              >
                <td className="px-3 py-2 font-mono">{String(it.stock_code ?? '')}</td>
                <td className="px-3 py-2">{String(it.stock_name ?? '')}</td>
                {screenshotType === 'transactions' && (
                  <>
                    <td className="px-3 py-2">
                      {it.action === 'buy' ? (
                        <span className="text-down">买入</span>
                      ) : (
                        <span className="text-up">卖出</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">{String(it.shares ?? '')}</td>
                    <td className="px-3 py-2 text-right font-mono">{String(it.price ?? '')}</td>
                    <td className="px-3 py-2 font-mono">{String(it.trade_date ?? '')}</td>
                  </>
                )}
                {screenshotType === 'position' && (
                  <>
                    <td className="px-3 py-2 text-right font-mono">{String(it.shares ?? '')}</td>
                    <td className="px-3 py-2 text-right font-mono">{String(it.cost_price ?? '')}</td>
                    <td className="px-3 py-2 text-right font-mono">{String(it.market_value ?? '')}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex justify-between">
        <Button variant="ghost" onClick={onRetake}>
          ↻ 重新识别
        </Button>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={reject} loading={busy}>
            取消
          </Button>
          <Button variant="primary" onClick={confirm} loading={busy}>
            ✓ 确认入库({items.length})
          </Button>
        </div>
      </div>
    </Card>
  );
}