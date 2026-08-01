'use client';

import { useState } from 'react';

import clsx from 'clsx';

import { apiPost } from '@/lib/api';
import { useUIStore } from '@/stores/useUIStore';

import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';

/**
 * 截图预览 + 确认/重试(P8.7 通用化)
 *
 * - **不按 screenshotType 分支**:遍历 items[0] 的 keys 自动生成列
 * - 字段名 → 中文标签(覆盖常见 key)
 * - 数字格式化:整数右对齐 + font-mono,百分比带 %,金额带 ¥
 * - 持仓 / 流水 / 自选股 / 自定义 LLM 输出都能正确显示
 */
const FIELD_LABELS: Record<string, string> = {
  stock_code: '代码',
  stock_name: '名称',
  action: '方向',
  shares: '股数',
  price: '价格',
  trade_date: '日期',
  cost_price: '成本价',
  market_value: '市值',
  current_price: '现价',
  profit: '盈亏',
  profit_ratio: '盈亏比(%)',
  note: '备注',
  screenshot_time: '截图时间',
};

const INT_FIELDS = new Set(['shares']);
const NUM_FIELDS = new Set(['profit', 'profit_ratio']);
const CURRENCY_FIELDS = new Set(['price', 'cost_price', 'current_price', 'market_value', 'profit']);

function labelOf(key: string): string {
  return FIELD_LABELS[key] ?? key;
}

function formatCell(key: string, raw: unknown): string {
  if (raw === null || raw === undefined || raw === '') return '—';
  if (INT_FIELDS.has(key)) {
    const n = Number(raw);
    return Number.isFinite(n) ? String(Math.trunc(n)) : String(raw);
  }
  if (CURRENCY_FIELDS.has(key)) {
    const n = Number(raw);
    return Number.isFinite(n) ? `¥${n.toFixed(2)}` : String(raw);
  }
  if (NUM_FIELDS.has(key)) {
    const n = Number(raw);
    if (!Number.isFinite(n)) return String(raw);
    const sign = n > 0 ? '+' : '';
    return `${sign}${n.toFixed(2)}`;
  }
  return String(raw);
}

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

  // 自动从 items[0] 推断列(排除 stock_code / stock_name 已固定在前面)
  const firstItem: Record<string, unknown> = items[0] ?? {};
  const allKeys = items.length > 0 ? Object.keys(firstItem) : [];
  const codeKey = 'stock_code';
  const nameKey = allKeys.includes('stock_name') ? 'stock_name' : undefined;
  const detailKeys = allKeys.filter(
    (k) => k !== codeKey && k !== nameKey && !k.startsWith('screenshot_'),
  );

  const isPositionLike =
    screenshotType === 'position' || screenshotType === 'holdings';
  const typeBadge = (
    <Badge variant={screenshotType === 'transactions' ? 'mid' : 'good'}>
      {screenshotType}
    </Badge>
  );

  const setCell = (rowIndex: number, key: string, value: string) => {
    setItems((prev) =>
      prev.map((it, i) => {
        if (i !== rowIndex) return it;
        const next = { ...it };
        if (key === 'shares') {
          const n = Number(value);
          if (Number.isFinite(n) && n > 0) next[key] = n;
        } else {
          next[key] = value;
        }
        return next;
      }),
    );
  };

  const confirm = async () => {
    setBusy(true);
    try {
      await apiPost(`/screenshot/${recordId}/confirm`, {
        items,
        screenshotType,
      });
      showToast({
        type: 'success',
        message: isPositionLike
          ? `已导入 ${items.length} 只持仓`
          : `已确认 ${items.length} 条入库`,
      });
      // v0.4.0:持仓导入后通知持仓区刷新
      if (isPositionLike) {
        window.dispatchEvent(new CustomEvent('positions-updated'));
      }
      onClose();
    } catch (e: unknown) {
      // 后端 detail.code(axios 拦截器标准化为 camelCase)
      const detail =
        (e as { response?: { data?: { detail?: { code?: string; message?: string } } } })
          .response?.data?.detail;
      if (detail?.code === 'MISSING_PRICE') {
        showToast({
          type: 'warning',
          message: detail.message ?? '缺少成本价,请补填后重试',
        });
      } else {
        showToast({ type: 'error', message: detail?.message ?? '确认失败,请重试' });
      }
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
        <h2 className="text-lg font-semibold flex items-center gap-2">
          预览识别结果
          {typeBadge}
        </h2>
        <button
          onClick={onClose}
          className="text-text-ter hover:text-text-pri text-xl"
        >
          ×
        </button>
      </header>

      <div className="text-sm text-text-sec">
        共识别{' '}
        <span className="font-mono font-semibold">{items.length}</span> 条记录
        {isPositionLike && (
          <span className="ml-2 text-warn text-xs">
            (将导入持仓,可点击表格数字补填/修改成本价)
          </span>
        )}
        ,请核对后确认。
      </div>

      <div className="overflow-x-auto border border-border-def rounded-sm">
        <table className="w-full text-sm">
          <thead className="bg-bg-subtle text-text-sec">
            <tr>
              <th className="text-left px-3 py-2 whitespace-nowrap">
                {labelOf(codeKey)}
              </th>
              {nameKey && (
                <th className="text-left px-3 py-2 whitespace-nowrap">
                  {labelOf(nameKey)}
                </th>
              )}
              {detailKeys.map((k) => (
                <th
                  key={k}
                  className={clsx(
                    'px-3 py-2 whitespace-nowrap',
                    INT_FIELDS.has(k) || NUM_FIELDS.has(k) || CURRENCY_FIELDS.has(k)
                      ? 'text-right'
                      : 'text-left',
                  )}
                >
                  {labelOf(k)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr
                key={i}
                className="border-t border-border-def hover:bg-bg-subtle"
              >
                <td className="px-3 py-2 font-mono whitespace-nowrap">
                  {String(it[codeKey] ?? '')}
                </td>
                {nameKey && (
                  <td className="px-3 py-2 whitespace-nowrap">
                    {String(it[nameKey] ?? '')}
                  </td>
                )}
                {detailKeys.map((k) => {
                  const editable =
                    isPositionLike && (k === 'shares' || k === 'price' || k === 'cost_price');
                  return (
                    <td
                      key={k}
                      className={clsx(
                        'px-3 py-2 whitespace-nowrap',
                        INT_FIELDS.has(k) || NUM_FIELDS.has(k) || CURRENCY_FIELDS.has(k)
                          ? 'text-right font-mono'
                          : '',
                      )}
                    >
                      {editable ? (
                        <input
                          defaultValue={String(it[k] ?? '')}
                          onBlur={(e) => setCell(i, k, e.target.value)}
                          className="w-24 text-right font-mono text-sm px-1 py-0.5 border border-border-def rounded-sm bg-bg-surface focus:border-accent"
                        />
                      ) : (
                        formatCell(k, it[k])
                      )}
                    </td>
                  );
                })}
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
          <Button
            variant="primary"
            onClick={confirm}
            loading={busy}
          >
            {isPositionLike
              ? `✓ 确认导入持仓(${items.length})`
              : `✓ 确认入库(${items.length})`}
          </Button>
        </div>
      </div>
    </Card>
  );
}