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
 */
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

  const fillExample = () => {
    setText(JSON.stringify({
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
    }, null, 2));
  };

  return (
    <div className="space-y-3">
      <div className="text-xs text-text-sec">
        将外网模型(豆包 / GPT-4V 等)返回的 JSON 粘贴到下方,字段说明见{' '}
        <button className="underline" onClick={fillExample}>示例</button>。
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={10}
        className="w-full font-mono text-xs p-2 border border-border-def rounded-sm bg-bg-surface"
        placeholder='{"screenshot_type": "...", "items": [...]}'
      />
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={fillExample}>填入示例</Button>
        <Button variant="primary" onClick={onSubmit} loading={loading}>
          解析
        </Button>
      </div>
    </div>
  );
}