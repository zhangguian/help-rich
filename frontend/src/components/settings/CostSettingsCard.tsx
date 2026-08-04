'use client';

import { useEffect, useState } from 'react';

import { apiGet, apiPut } from '@/lib/api';
import type { CostSettings } from '@/lib/types';
import { useUIStore } from '@/stores/useUIStore';

import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';

/**
 * 交易费用设置卡(GB-001 IR-4)
 *
 * - 开关默认关闭:所有盈亏展示不含费用(保持旧版行为)
 * - 开启后:计算器/年账单双口径(毛/净)展示
 * - 费率默认 A 股常见值,可调
 */
const RATE_FIELDS: Array<{
  key: keyof Pick<
    CostSettings,
    'commissionRate' | 'minCommission' | 'stampTaxRate' | 'transferFeeRate'
  >;
  label: string;
  hint: string;
}> = [
  { key: 'commissionRate', label: '佣金率', hint: '默认 0.00025(万2.5)' },
  { key: 'minCommission', label: '最低佣金(元)', hint: '默认 5.00' },
  { key: 'stampTaxRate', label: '印花税率(卖出)', hint: '默认 0.0005(0.05%)' },
  { key: 'transferFeeRate', label: '过户费率(双向)', hint: '默认 0.00001(0.001%)' },
];

export function CostSettingsCard() {
  const showToast = useUIStore((s) => s.showToast);
  const [settings, setSettings] = useState<CostSettings | null>(null);
  const [draft, setDraft] = useState<CostSettings | null>(null);
  const [saving, setSaving] = useState(false);

  const refresh = async () => {
    try {
      const s = await apiGet<CostSettings>('/cost/settings');
      setSettings(s);
      setDraft(s);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const saved = await apiPut<CostSettings>('/cost/settings', draft);
      setSettings(saved);
      setDraft(saved);
      showToast({
        type: 'success',
        message: saved.enabled ? '费用计算已开启(双口径展示)' : '费用计算已关闭',
      });
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: { message?: string } } } })
        ?.response?.data?.detail;
      showToast({ type: 'error', message: detail?.message ?? '保存失败' });
    } finally {
      setSaving(false);
    }
  };

  if (!settings || !draft) {
    return <Card className="h-32 animate-pulse bg-bg-subtle" />;
  }

  const setField = (
    key: keyof CostSettings,
    value: string | boolean,
  ) => setDraft((d) => (d ? { ...d, [key]: value } : d));

  return (
    <Card padding="md" className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-semibold flex items-center gap-2">
            💰 交易费用(GB-001 IR-4)
            {draft.enabled ? (
              <Badge variant="good">已开启 · 双口径</Badge>
            ) : (
              <Badge variant="muted">默认关闭</Badge>
            )}
          </div>
          <p className="text-xs text-text-sec mt-1">
            开启后计算器 / 年账单按「含费 / 不含费」双口径展示,佣金印花税不再被忽略
          </p>
        </div>
        <button
          onClick={() => setField('enabled', !draft.enabled)}
          className={`relative w-11 h-6 rounded-full transition-colors ${
            draft.enabled ? 'bg-accent' : 'bg-border-def'
          }`}
          aria-label="切换费用计算"
        >
          <span
            className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-all ${
              draft.enabled ? 'left-[22px]' : 'left-0.5'
            }`}
          />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {RATE_FIELDS.map((f) => (
          <label key={f.key} className="block">
            <span className="text-xs text-text-sec">{f.label}</span>
            <input
              type="text"
              value={draft[f.key] as string}
              onChange={(e) => setField(f.key, e.target.value)}
              disabled={!draft.enabled}
              className="mt-1 w-full px-3 py-1.5 border border-border-def rounded-sm font-mono text-sm bg-bg-surface disabled:opacity-50"
            />
            <span className="text-[11px] text-text-ter">{f.hint}</span>
          </label>
        ))}
      </div>

      <div className="flex justify-end">
        <Button size="sm" variant="primary" onClick={save} loading={saving}>
          保存
        </Button>
      </div>
    </Card>
  );
}
