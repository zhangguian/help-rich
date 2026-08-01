'use client';

import { useState } from 'react';

import { apiBaseUrl, apiGet, apiPost } from '@/lib/api';
import type { DiagnoseOut } from '@/lib/types';
import { useUIStore } from '@/stores/useUIStore';

import { Button } from '../ui/Button';
import { Card } from '../ui/Card';

import { ScreenshotPastePanel } from './ScreenshotPastePanel';
import { ScreenshotPreview } from './ScreenshotPreview';

/**
 * 截图上传向导(P8.6)
 *
 * 步骤:
 * 1. 选择文件(jpg/png/webp,≤5MB)+ 类型(持仓 / 流水 / 自选股)
 * 2. 上传 OCR + LLM 识别(进度提示)
 * 3. 预览表格 + 确认/重试/降级粘贴
 */
type Mode = 'upload' | 'paste';

export function ScreenshotWizard({ onClose }: { onClose: () => void }) {
  const showToast = useUIStore((s) => s.showToast);
  const [mode, setMode] = useState<Mode>('upload');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [recordId, setRecordId] = useState<number | null>(null);
  const [screenshotType, setScreenshotType] = useState<
    'position' | 'transactions' | 'watchlist' | null
  >(null);
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) {
      showToast({ type: 'error', message: '文件超过 5MB,请压缩后重试' });
      return;
    }
    if (!/\.(jpe?g|png|webp)$/i.test(f.name)) {
      showToast({ type: 'error', message: '暂只支持 jpg / png / webp 格式' });
      return;
    }
    setFile(f);
  };

  const onUpload = async () => {
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const r = await fetch(`${apiBaseUrl()}/screenshot/upload`, {
        method: 'POST',
        body: form,
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        const code = err.detail?.code ?? 'UPLOAD_FAILED';
        const msg = err.detail?.message ?? `上传失败 (${r.status})`;
        showToast({ type: 'error', message: msg });
        // OCR 失败/无 Key → 自动切换到粘贴模式
        if (code === 'OCR_FAILED' || code === 'NO_KEY' || code === 'OCR_EMPTY') {
          setMode('paste');
        }
        return;
      }
      const data = (await r.json()) as {
        recordId: number;
        items: Array<Record<string, unknown>>;
        screenshotType: string | null;
      };
      setRecordId(data.recordId);
      setItems(data.items);
      setScreenshotType((data.screenshotType as typeof screenshotType) ?? null);
      if (data.items.length === 0) {
        showToast({
          type: 'warning',
          message: 'OCR 未识别出有效记录,可粘贴 JSON 降级',
        });
        setMode('paste');
      }
    } catch (e) {
      showToast({ type: 'error', message: '上传失败,请重试' });
    } finally {
      setUploading(false);
    }
  };

  const onPasteResult = (id: number, type: string, parsed: Array<Record<string, unknown>>) => {
    setRecordId(id);
    setScreenshotType(type as typeof screenshotType);
    setItems(parsed);
  };

  const reset = () => {
    setFile(null);
    setRecordId(null);
    setItems([]);
    setScreenshotType(null);
    setMode('upload');
  };

  if (recordId && screenshotType) {
    return (
      <ScreenshotPreview
        recordId={recordId}
        screenshotType={screenshotType}
        items={items}
        onRetake={reset}
        onClose={onClose}
      />
    );
  }

  return (
    <Card padding="lg" className="space-y-4">
      <header className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">截图识别</h2>
        <button onClick={onClose} className="text-text-ter hover:text-text-pri text-xl">
          ×
        </button>
      </header>

      <div className="flex gap-2 text-sm">
        <Button
          size="sm"
          variant={mode === 'upload' ? 'primary' : 'ghost'}
          onClick={() => setMode('upload')}
        >
          📷 上传截图
        </Button>
        <Button
          size="sm"
          variant={mode === 'paste' ? 'primary' : 'ghost'}
          onClick={() => setMode('paste')}
        >
          📋 粘贴 JSON
        </Button>
      </div>

      {mode === 'upload' ? (
        <div className="space-y-3">
          <div className="border-2 border-dashed border-border-def rounded-md p-6 text-center">
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={onFileChange}
              className="hidden"
              id="screenshot-file"
            />
            <label
              htmlFor="screenshot-file"
              className="cursor-pointer text-text-sec hover:text-text-pri"
            >
              {file ? (
                <span>已选:<span className="font-mono">{file.name}</span> ({(file.size / 1024).toFixed(0)} KB)</span>
              ) : (
                <>
                  <div className="text-2xl mb-2">📂</div>
                  <div>点击选择截图或拖拽到此处</div>
                  <div className="text-xs text-text-ter mt-1">
                    支持 jpg / png / webp,≤5MB
                  </div>
                </>
              )}
            </label>
          </div>
          <div className="flex justify-end">
            <Button
              variant="primary"
              onClick={onUpload}
              disabled={!file || uploading}
              loading={uploading}
            >
              开始识别
            </Button>
          </div>
        </div>
      ) : (
        <ScreenshotPastePanel onResult={onPasteResult} />
      )}
    </Card>
  );
}