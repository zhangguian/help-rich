'use client';

import { useEffect, useState } from 'react';

import { apiGet, apiPost, apiPut } from '@/lib/api';
import type { LlmKeysStatus, LlmTestResponse } from '@/lib/types';
import { useUIStore } from '@/stores/useUIStore';

import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';

/**
 * LLM Key 输入卡(P7.12,ui-ux §13.6.1)
 *
 * - 3 个 Provider 各一行:输入框(密码) + [显示] + [测试连接] + 状态色
 * - 状态:未配置(灰) / 已配置(绿) / 测试中(黄) / 测试失败(红)
 * - 保存只触发 PUT,不回显明文
 */
type Provider = 'deepseek' | 'minimax' | 'doubao';

const LABELS: Record<Provider, string> = {
  deepseek: 'DeepSeek',
  minimax: 'MiniMax',
  doubao: '豆包',
};

export function LlmKeysCard() {
  const showToast = useUIStore((s) => s.showToast);
  const [status, setStatus] = useState<LlmKeysStatus | null>(null);
  const [show, setShow] = useState<Record<Provider, boolean>>({
    deepseek: false,
    minimax: false,
    doubao: false,
  });
  const [keys, setKeys] = useState<Record<Provider, string>>({
    deepseek: '',
    minimax: '',
    doubao: '',
  });
  const [testing, setTesting] = useState<Provider | null>(null);

  const refresh = async () => {
    try {
      const s = await apiGet<LlmKeysStatus>('/llm/keys');
      setStatus(s);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const saveOne = async (provider: Provider) => {
    const value = keys[provider];
    if (!value) {
      showToast({ type: 'error', message: '请先输入 Key' });
      return;
    }
    try {
      await apiPut('/llm/keys', {
        deepseek: provider === 'deepseek' ? value : '',
        minimax: provider === 'minimax' ? value : '',
        doubao: provider === 'doubao' ? value : '',
      });
      showToast({ type: 'success', message: `${LABELS[provider]} Key 已保存` });
      setKeys((prev) => ({ ...prev, [provider]: '' }));
      refresh();
    } catch {
      showToast({ type: 'error', message: '保存失败' });
    }
  };

  const test = async (provider: Provider) => {
    setTesting(provider);
    try {
      const r = await apiPost<LlmTestResponse>('/llm/test', { provider });
      if (r.ok) {
        showToast({
          type: 'success',
          message: `${LABELS[provider]} 连接成功 (${r.latencyMs ?? '?'}ms)`,
        });
      } else {
        showToast({
          type: 'error',
          message: `${LABELS[provider]} 失败:${r.error ?? '未知'}`,
        });
      }
    } catch {
      showToast({ type: 'error', message: '测试失败' });
    } finally {
      setTesting(null);
    }
  };

  if (!status) {
    return <Card className="h-32 animate-pulse bg-bg-subtle" />;
  }

  return (
    <Card padding="md" className="space-y-3">
      <div>
        <div className="font-semibold flex items-center gap-2">
          🔑 LLM API Key
          <Badge variant="muted">Fernet 加密</Badge>
        </div>
        <p className="text-xs text-text-sec mt-1">
          Key 用 Fernet 加密后入库,前端从不接收明文
        </p>
      </div>

      {(['deepseek', 'minimax', 'doubao'] as Provider[]).map((p) => {
        const configured = status[p];
        return (
          <div
            key={p}
            className="border border-border-def rounded-sm p-3 space-y-2"
          >
            <div className="flex items-center justify-between">
              <div className="font-medium flex items-center gap-2">
                {LABELS[p]}
                {configured ? (
                  <Badge variant="good">已配置</Badge>
                ) : (
                  <Badge variant="muted">未配置</Badge>
                )}
              </div>
            </div>

            <div className="flex gap-2">
              <input
                type={show[p] ? 'text' : 'password'}
                value={keys[p]}
                onChange={(e) =>
                  setKeys((prev) => ({ ...prev, [p]: e.target.value }))
                }
                placeholder={
                  configured ? '•••••••(已配置,留空保持)' : '请输入 API Key'
                }
                className="flex-1 px-3 py-1.5 border border-border-def rounded-sm font-mono text-sm bg-bg-surface"
              />
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  setShow((s) => ({ ...s, [p]: !s[p] }))
                }
              >
                {show[p] ? '隐藏' : '显示'}
              </Button>
              <Button
                size="sm"
                variant="primary"
                onClick={() => saveOne(p)}
                disabled={!keys[p]}
              >
                保存
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => test(p)}
                disabled={!configured || testing === p}
                loading={testing === p}
              >
                测试连接
              </Button>
            </div>
          </div>
        );
      })}
    </Card>
  );
}