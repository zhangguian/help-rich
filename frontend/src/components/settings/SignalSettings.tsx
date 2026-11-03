'use client';

/**
 * 盘中信号设置(盘中持仓信号 · 桌面通知 ADR-0007)
 *
 * **范围**:只对**持仓股**生效(后端每次现取持仓,不缓存代码集合)。
 * **桌面通知由后端弹** —— 浏览器关着也能收到;这里只负责配阈值与渠道。
 *
 * 阈值口径(与后端 `modules/signal/service.py::SignalConfig` 一一对应):
 * - 急速:窗口秒数内涨跌幅 ≥ 阈值
 * - 突破:相对昨收 ±阈值(带 0.5% 迟滞防抖)
 * - 冷却:同类信号多少秒内不重复;日限流:单票单日上限
 */
import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import {
  fetchSignalConfig,
  updateSignalConfig,
  testSignalToast,
  type SignalConfig,
} from '@/lib/api/advanced';
import { useUIStore } from '@/stores/useUIStore';

/** 可选投递渠道(桌面通知零凭据,其余需在「通知渠道」里已启用) */
const CHANNEL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'desktop', label: '桌面通知' },
  { value: 'console', label: '终端日志' },
  { value: 'dingtalk', label: '钉钉' },
  { value: 'wecom', label: '企业微信' },
  { value: 'bark', label: 'Bark' },
  { value: 'webhook', label: 'Webhook' },
];

/** 四类信号各自的中文名(与后端 kind 对应) */
const KIND_LABELS: Array<{ key: keyof SignalConfig; label: string }> = [
  { key: 'enableVelocity', label: '急速拉升 / 下跌' },
  { key: 'enableBreakout', label: '涨幅 / 跌幅突破' },
  { key: 'enableTPoint', label: '预测做T点(卖出 / 买回)' },
  { key: 'enableBuyPoint', label: '预测买点' },
];

export function SignalSettings() {
  const showToast = useUIStore((s) => s.showToast);
  const [config, setConfig] = useState<SignalConfig | null>(null);
  const [notes, setNotes] = useState<Record<string, string[]>>({});
  const [levelsUpdatedAt, setLevelsUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchSignalConfig();
      setConfig(data.config);
      setNotes(data.runtime?.notes ?? {});
      setLevelsUpdatedAt(data.runtime?.levelsUpdatedAt ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const patch = async (payload: Partial<SignalConfig>) => {
    if (!config) return;
    setBusy(true);
    setError('');
    try {
      const data = await updateSignalConfig(payload);
      setConfig(data.config);
      showToast({ type: 'success', message: '已保存' });
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };

  const doTest = async () => {
    setBusy(true);
    try {
      const r = await testSignalToast();
      showToast({
        type: r.ok ? 'success' : 'error',
        message: r.ok ? '桌面通知已发送,请看右下角' : `发送失败:${r.detail}`,
      });
    } catch (e) {
      showToast({ type: 'error', message: e instanceof Error ? e.message : '测试失败' });
    } finally {
      setBusy(false);
    }
  };

  const toggleChannel = (value: string) => {
    if (!config) return;
    const channels = config.channels.includes(value)
      ? config.channels.filter((c) => c !== value)
      : [...config.channels, value];
    void patch({ channels });
  };

  if (loading) {
    return (
      <Card padding="lg">
        <div className="text-sm text-text-sec">加载盘中信号配置中…</div>
      </Card>
    );
  }

  if (!config) {
    return (
      <Card padding="lg">
        <div className="text-sm text-danger">{error || '配置加载失败'}</div>
      </Card>
    );
  }

  const noteEntries = Object.entries(notes).filter(([, v]) => v.length > 0);

  return (
    <Card padding="lg" className="space-y-4">
      <header>
        <h2 className="text-base font-semibold">盘中信号 · 桌面通知</h2>
        <p className="mt-1 text-xs text-text-sec">
          只对**持仓股**生效。急速拉升/下跌、涨跌幅突破、预测做T点与预测买点命中时,
          由**后端**直接弹 Windows 桌面通知 —— 浏览器关着也能收到。
        </p>
      </header>

      {error && (
        <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void patch({ enabled: !config.enabled })}
          disabled={busy}
          className={clsx(
            'rounded px-2 py-1 text-xs transition disabled:opacity-50',
            config.enabled
              ? 'border border-border-def text-text-sec hover:bg-bg-elevated'
              : 'bg-accent text-bg-base hover:opacity-90',
          )}
        >
          {config.enabled ? '总开关:已开启' : '总开关:已关闭'}
        </button>
        <button
          type="button"
          onClick={() => void doTest()}
          disabled={busy}
          className="rounded border border-border-def px-2 py-1 text-xs text-text-sec hover:bg-bg-elevated disabled:opacity-50"
        >
          测试桌面通知
        </button>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {KIND_LABELS.map((k) => (
          <label key={String(k.key)} className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={Boolean(config[k.key])}
              onChange={(e) => void patch({ [k.key]: e.target.checked } as Partial<SignalConfig>)}
              disabled={busy}
              className="accent-[var(--color-accent)]"
            />
            <span className="text-text-pri">{k.label}</span>
          </label>
        ))}
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <label className="space-y-1 text-[11px]">
          <span className="text-text-ter">急速判定窗口(秒)</span>
          <input
            type="number"
            min={5}
            max={3600}
            value={config.velocityWindowSec}
            onChange={(e) =>
              setConfig({ ...config, velocityWindowSec: Number(e.target.value) || 60 })
            }
            className="w-full rounded-md border border-border-def bg-bg-elevated px-2 py-1.5 text-xs text-text-pri outline-none focus:border-accent"
          />
        </label>
        <label className="space-y-1 text-[11px]">
          <span className="text-text-ter">急速判定幅度(%)</span>
          <input
            type="number"
            min={0.1}
            max={20}
            step={0.1}
            value={config.velocityPct}
            onChange={(e) => setConfig({ ...config, velocityPct: Number(e.target.value) || 1.5 })}
            className="w-full rounded-md border border-border-def bg-bg-elevated px-2 py-1.5 text-xs text-text-pri outline-none focus:border-accent"
          />
        </label>
        <label className="space-y-1 text-[11px]">
          <span className="text-text-ter">涨幅突破阈值(%,相对昨收)</span>
          <input
            type="number"
            min={0.5}
            max={50}
            step={0.5}
            value={config.breakoutUpPct}
            onChange={(e) =>
              setConfig({ ...config, breakoutUpPct: Number(e.target.value) || 5 })
            }
            className="w-full rounded-md border border-border-def bg-bg-elevated px-2 py-1.5 text-xs text-text-pri outline-none focus:border-accent"
          />
        </label>
        <label className="space-y-1 text-[11px]">
          <span className="text-text-ter">跌幅突破阈值(%,相对昨收)</span>
          <input
            type="number"
            min={-50}
            max={-0.5}
            step={0.5}
            value={config.breakoutDownPct}
            onChange={(e) =>
              setConfig({ ...config, breakoutDownPct: Number(e.target.value) || -5 })
            }
            className="w-full rounded-md border border-border-def bg-bg-elevated px-2 py-1.5 text-xs text-text-pri outline-none focus:border-accent"
          />
        </label>
        <label className="space-y-1 text-[11px]">
          <span className="text-text-ter">同类信号冷却(秒)</span>
          <input
            type="number"
            min={0}
            max={86400}
            value={config.cooldownSec}
            onChange={(e) => setConfig({ ...config, cooldownSec: Number(e.target.value) || 0 })}
            className="w-full rounded-md border border-border-def bg-bg-elevated px-2 py-1.5 text-xs text-text-pri outline-none focus:border-accent"
          />
        </label>
        <label className="space-y-1 text-[11px]">
          <span className="text-text-ter">单票单日上限(次)</span>
          <input
            type="number"
            min={1}
            max={100}
            value={config.dailyLimit}
            onChange={(e) => setConfig({ ...config, dailyLimit: Number(e.target.value) || 1 })}
            className="w-full rounded-md border border-border-def bg-bg-elevated px-2 py-1.5 text-xs text-text-pri outline-none focus:border-accent"
          />
        </label>
      </div>

      <button
        type="button"
        onClick={() => void patch(config)}
        disabled={busy}
        className="rounded border border-border-def px-2 py-1 text-xs text-text-sec hover:bg-bg-elevated disabled:opacity-50"
      >
        保存阈值
      </button>

      <div className="space-y-1.5">
        <div className="text-xs font-medium">投递渠道</div>
        <div className="flex flex-wrap gap-3">
          {CHANNEL_OPTIONS.map((c) => (
            <label key={c.value} className="flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={config.channels.includes(c.value)}
                onChange={() => toggleChannel(c.value)}
                disabled={busy}
                className="accent-[var(--color-accent)]"
              />
              <span className="text-text-pri">{c.label}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="text-xs font-medium">
          今日触发价
          {levelsUpdatedAt && (
            <span className="ml-2 font-normal text-text-ter">
              最近重算:{new Date(levelsUpdatedAt).toLocaleString('zh-CN')}
            </span>
          )}
        </div>
        {noteEntries.length === 0 ? (
          <p className="text-[11px] text-text-ter">暂无「今日不适合做T / 做网格」的持仓票。</p>
        ) : (
          <ul className="space-y-1">
            {noteEntries.map(([code, list]) => (
              <li key={code} className="text-[11px] text-text-sec">
                <span className="font-medium text-text-pri">{code}</span>:{list.join(';')}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
