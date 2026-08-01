'use client';

import { useEffect, useState } from 'react';

import { apiGet, apiPost } from '@/lib/api';
import type { LlmProviderItem, LlmSettingsOut } from '@/lib/types';
import { useUIStore } from '@/stores/useUIStore';

import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';

/**
 * Provider 设置卡(P7.11)
 *
 * - 列 3 个 Provider(name / model / configured)
 * - 当前激活高亮 + 可一键切换
 * - 状态色:已配置(绿)/未配置(灰)
 */
export function LlmProviderCard() {
  const showToast = useUIStore((s) => s.showToast);
  const [items, setItems] = useState<LlmProviderItem[]>([]);
  const [active, setActive] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const [prov, setting] = await Promise.all([
        apiGet<{ items: LlmProviderItem[] }>('/llm/providers'),
        apiGet<LlmSettingsOut>('/llm/settings'),
      ]);
      setItems(prov.items);
      setActive(setting.activeProvider);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const switchTo = async (name: string) => {
    if (name === active) return;
    setSwitching(name);
    try {
      await apiPost<LlmSettingsOut>('/llm/settings', { activeProvider: name });
      setActive(name);
      showToast({ type: 'success', message: `已切换到 ${name}` });
    } catch (e) {
      showToast({ type: 'error', message: '切换失败' });
    } finally {
      setSwitching(null);
    }
  };

  return (
    <Card padding="md" className="space-y-3">
      <div>
        <div className="font-semibold flex items-center gap-2">
          🤖 LLM Provider
          <Badge variant="muted">v0.2 多 Provider</Badge>
        </div>
        <p className="text-xs text-text-sec mt-1">
          切换当前激活的 LLM Provider;A/B 对比评语质量
        </p>
      </div>

      {loading && <div className="h-16 bg-bg-subtle rounded-sm animate-pulse" />}

      {!loading && (
        <div className="space-y-2">
          {items.map((p) => {
            const isActive = p.name === active;
            const canSwitch = p.configured;
            return (
              <div
                key={p.name}
                className={`flex items-center justify-between p-3 rounded-sm border ${
                  isActive
                    ? 'border-accent-primary bg-accent-subtle'
                    : 'border-border-def'
                }`}
              >
                <div>
                  <div className="font-medium flex items-center gap-2">
                    {p.name}
                    {isActive && <Badge variant="good">激活中</Badge>}
                    {!p.configured && <Badge variant="bad">未配置 Key</Badge>}
                  </div>
                  <div className="text-xs text-text-sec font-mono mt-0.5">
                    {p.model}
                  </div>
                </div>
                <Button
                  size="sm"
                  variant={isActive ? 'secondary' : 'primary'}
                  disabled={!canSwitch || switching === p.name}
                  onClick={() => switchTo(p.name)}
                  loading={switching === p.name}
                >
                  {isActive ? '当前' : canSwitch ? '切换' : '需先配置'}
                </Button>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}