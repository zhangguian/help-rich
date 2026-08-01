'use client';

import { useState } from 'react';

import { apiGet, apiPost } from '@/lib/api';
import { useUIStore } from '@/stores/useUIStore';

import { Button } from '../ui/Button';
import { Card } from '../ui/Card';

/**
 * 数据导出/导入卡(P7.3,ui-ux §13.1)
 *
 * - 导出:点击 → GET /admin/export → 浏览器下载 JSON 文件
 * - 导入:<input type=file> → POST /admin/import (replace)
 *   - 危险操作:二次确认弹窗
 */
export function ExportImportCard() {
  const showToast = useUIStore((s) => s.showToast);
  const [importing, setImporting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingPayload, setPendingPayload] = useState<unknown>(null);

  const onExport = async () => {
    try {
      const res = await apiGet<{ version: string; exported_at: string; tables: Record<string, unknown[]> }>(
        '/admin/export',
      );
      const blob = new Blob([JSON.stringify(res, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `rich-export-${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast({ type: 'success', message: '导出已开始下载' });
    } catch {
      showToast({ type: 'error', message: '导出失败' });
    }
  };

  const onImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      setPendingPayload(payload);
      setConfirmOpen(true);
    } catch {
      showToast({ type: 'error', message: 'JSON 解析失败' });
    }
    e.target.value = ''; // 允许重复选择同文件
  };

  const doImport = async () => {
    setConfirmOpen(false);
    setImporting(true);
    try {
      const r = await apiPost<{ ok: boolean; imported: Record<string, number> }>(
        '/admin/import',
        { payload: pendingPayload, mode: 'replace' },
      );
      const total = Object.values(r.imported).reduce((a, b) => a + b, 0);
      showToast({
        type: 'success',
        message: `导入完成:共 ${total} 条记录`,
      });
    } catch {
      showToast({ type: 'error', message: '导入失败' });
    } finally {
      setImporting(false);
      setPendingPayload(null);
    }
  };

  return (
    <>
      <Card padding="md" className="space-y-3">
        <div>
          <div className="font-semibold flex items-center gap-2">
            💾 数据备份与还原
          </div>
          <p className="text-xs text-text-sec mt-1">
            导出全部数据为 JSON;导入将**清空现有数据**后全量替换
          </p>
        </div>

        <div className="flex flex-wrap gap-3">
          <Button variant="primary" onClick={onExport}>
            📥 导出 JSON
          </Button>
          <label className="inline-flex items-center">
            <Button
              variant="secondary"
              loading={importing}
              onClick={() => document.getElementById('import-file-input')?.click()}
            >
              📤 导入 JSON
            </Button>
            <input
              id="import-file-input"
              type="file"
              accept="application/json,.json"
              onChange={onImportFile}
              className="hidden"
            />
          </label>
        </div>
      </Card>

      {confirmOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              setConfirmOpen(false);
              setPendingPayload(null);
            }
          }}
        >
          <div className="bg-bg-surface rounded-md shadow-lg p-6 max-w-sm w-full mx-4 space-y-4">
            <h3 className="font-semibold text-lg text-warn">⚠ 确认导入</h3>
            <p className="text-sm text-text-sec">
              导入会**清空所有现有数据**(交易 / 持仓 / 评分 / 止损 / 自选股 / 截图 / LLM Key)后,从备份还原。
              <br />
              <span className="text-warn">此操作不可撤销,请确认已导出当前数据。</span>
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => { setConfirmOpen(false); setPendingPayload(null); }}>
                取消
              </Button>
              <Button variant="danger" onClick={doImport} loading={importing}>
                确认清空并导入
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}