'use client';

import { useState } from 'react';

import { apiPost } from '@/lib/api';
import { useUIStore } from '@/stores/useUIStore';

import { Button } from '../ui/Button';

/**
 * 截图粘贴 JSON 降级面板(P8.8)
 *
 * 适用场景:
 * - OCR 失败 / 无 Key
 * - 用户在外网(豆包 / GPT-4V)识图后,把 JSON 粘过来
 *
 * 三选一填入示例(transactions / holdings / watchlist),覆盖截图识别主要场景:
 * - transactions:流水,confirm 后写入 transactions 表
 * - holdings  :持仓快照,confirm 后**拒绝入库**(持仓是视图),用于预览展示
 * - watchlist :自选股,confirm 后写入 watchlist 表
 */
const EXAMPLES: Record<string, object> = {
  transactions: {
    screenshot_type: 'transactions',
    items: [
      {
        stock_code: '600519.SH',
        stock_name: '贵州茅台',
        action: 'buy',
        shares: 100,
        price: '1450.000',
        trade_date: '2026-07-20',
      },
    ],
  },
  holdings: {
    screenshot_type: 'holdings',
    note: '本截图为持仓页面而非交易成交记录,price 字段为持仓成本价',
    screenshot_time: '2026-08-01 17:29',
    items: [
      {
        stock_code: '001896.SZ',
        stock_name: '豫能控股',
        shares: 300,
        price: '18.500',
        current_price: '12.020',
        profit: -1944.06,
        profit_ratio: -35.027,
      },
      {
        stock_code: '000807.SZ',
        stock_name: '云铝股份',
        shares: 200,
        price: '18.130',
        current_price: '26.620',
        profit: 1698.00,
        profit_ratio: 46.828,
      },
      {
        stock_code: '000066.SZ',
        stock_name: '中国长城',
        shares: 400,
        price: '16.797',
        current_price: '13.740',
        profit: -1222.88,
        profit_ratio: -18.200,
      },
    ],
  },
  watchlist: {
    screenshot_type: 'watchlist',
    items: [
      { stock_code: '600519.SH', stock_name: '贵州茅台' },
      { stock_code: '300750.SZ', stock_name: '宁德时代' },
      { stock_code: '000858.SZ', stock_name: '五粮液' },
    ],
  },
};

export function ScreenshotPastePanel({
  onResult,
}: {
  onResult: (
    recordId: number,
    screenshotType: string,
    items: Array<Record<string, unknown>>,
  ) => void;
}) {
  const showToast = useUIStore((s) => s.showToast);
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);

  const fillExample = (key: 'transactions' | 'holdings' | 'watchlist') => {
    setText(JSON.stringify(EXAMPLES[key], null, 2));
  };

  const onSubmit = async () => {
    if (!text.trim()) {
      showToast({ type: 'error', message: '请粘贴 JSON' });
      return;
    }
    setLoading(true);
    try {
      const r = await apiPost<{
        recordId: number;
        screenshotType: string | null;
        items: Array<Record<string, unknown>>;
      }>('/screenshot/parse-paste', { rawJson: text });
      onResult(r.recordId, r.screenshotType ?? 'position', r.items);
    } catch (e) {
      showToast({ type: 'error', message: 'JSON 格式错误或字段缺失' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="text-xs text-text-sec">
        将外网模型(豆包 / GPT-4V 等)返回的 JSON 粘贴到下方,字段说明见下方示例:
      </div>

      {/* 三选一示例按钮组 */}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="ghost" onClick={() => fillExample('transactions')}>
          📋 流水示例
        </Button>
        <Button size="sm" variant="ghost" onClick={() => fillExample('holdings')}>
          💼 持仓示例
        </Button>
        <Button size="sm" variant="ghost" onClick={() => fillExample('watchlist')}>
          ⭐ 自选股示例
        </Button>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={12}
        className="w-full font-mono text-xs p-2 border border-border-def rounded-sm bg-bg-surface"
        placeholder='{"screenshot_type": "...", "items": [...]}'
      />
      <div className="flex justify-end">
        <Button variant="primary" onClick={onSubmit} loading={loading}>
          解析
        </Button>
      </div>
    </div>
  );
}