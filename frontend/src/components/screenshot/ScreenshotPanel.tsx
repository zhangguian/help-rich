'use client';

import { useState } from 'react';

import { ScreenshotWizard } from './ScreenshotWizard';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { Badge } from '../ui/Badge';

/**
 * 截图功能入口卡(P8.9 设置页 + 首页快捷入口)
 */
export function ScreenshotPanel() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Card padding="md" className="flex items-center justify-between">
        <div>
          <div className="font-semibold flex items-center gap-2">
            📷 截图识别
            <Badge variant="mid">PaddleOCR</Badge>
          </div>
          <p className="text-xs text-text-sec mt-1">
            上传同花顺 App 截图,自动识别持仓 / 流水 / 自选股
          </p>
        </div>
        <Button variant="primary" onClick={() => setOpen(true)}>
          开始识别
        </Button>
      </Card>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div className="w-full max-w-2xl">
            <ScreenshotWizard onClose={() => setOpen(false)} />
          </div>
        </div>
      )}
    </>
  );
}