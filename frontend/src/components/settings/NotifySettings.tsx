'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import {
  fetchNotifyChannels,
  saveNotifyChannel,
  testNotifyChannel,
  type NotifyChannelConfig,
} from '@/lib/api/advanced';

/** 各渠道需要的凭据字段(与后端 config_service 一致) */
const CHANNEL_FIELDS: Record<string, Array<{ key: string; label: string; secret?: boolean }>> = {
  dingtalk: [{ key: 'webhook', label: 'Webhook 地址', secret: true }],
  wecom: [{ key: 'webhook', label: 'Webhook 地址', secret: true }],
  bark: [
    { key: 'server', label: '服务器地址(默认 api.day.app)' },
    { key: 'device_key', label: 'Device Key', secret: true },
  ],
  webhook: [
    { key: 'url', label: '接收地址', secret: true },
    { key: 'secret', label: '签名密钥(可选)', secret: true },
  ],
  console: [],
};

/**
 * 通知渠道设置(阶段1)
 *
 * 安全约定:凭据**只写不读**。列表接口只返回 `configured: true/false`,
 * 不回传明文;因此输入框永远留空,占位符提示"已配置/未配置"。
 * 这是有意的取舍:让用户看得见 Key 就等于任何 XSS 都能偷走它。
 */
export function NotifySettings() {
  const [channels, setChannels] = useState<NotifyChannelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchNotifyChannels();
      setChannels(data.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const setField = (channel: string, key: string, value: string) => {
    setDrafts((prev) => ({ ...prev, [channel]: { ...(prev[channel] ?? {}), [key]: value } }));
  };

  const save = async (channel: string, enabled: boolean) => {
    setBusy(channel);
    setError('');
    try {
      await saveNotifyChannel(channel, { enabled, config: drafts[channel] ?? {} });
      setDrafts((prev) => ({ ...prev, [channel]: {} }));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(null);
    }
  };

  const doTest = async (channel: string) => {
    setBusy(channel);
    try {
      const r = await testNotifyChannel(channel);
      setTestResult((prev) => ({
        ...prev,
        [channel]: r.ok ? '✅ 测试消息已发送' : `❌ ${r.detail ?? '发送失败'}`,
      }));
    } catch (e) {
      setTestResult((prev) => ({
        ...prev,
        [channel]: `❌ ${e instanceof Error ? e.message : '测试失败'}`,
      }));
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <Card padding="lg">
        <div className="text-sm text-text-sec">加载渠道中…</div>
      </Card>
    );
  }

  return (
    <Card padding="lg" className="space-y-4">
      <header>
        <h2 className="text-base font-semibold">通知渠道</h2>
        <p className="mt-1 text-xs text-text-sec">
          提醒与盘前简报会推送到已启用的渠道。凭据加密存库,保存后不再回显。
        </p>
      </header>

      {error && (
        <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </div>
      )}

      <ul className="space-y-3">
        {channels.map((ch) => {
          const fields = CHANNEL_FIELDS[ch.channel] ?? [];
          const draft = drafts[ch.channel] ?? {};
          return (
            <li key={ch.channel} className="rounded-md border border-border-base p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{ch.label}</span>
                  <span
                    className={clsx(
                      'rounded px-1.5 py-0.5 text-[10px]',
                      ch.enabled ? 'bg-accent/15 text-accent' : 'bg-bg-elev text-text-ter',
                    )}
                  >
                    {ch.enabled ? '已启用' : '未启用'}
                  </span>
                  {ch.configured && (
                    <span className="rounded bg-bg-elev px-1.5 py-0.5 text-[10px] text-text-sec">
                      已配置凭据
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void doTest(ch.channel)}
                    disabled={busy === ch.channel}
                    className="rounded border border-border-base px-2 py-1 text-xs text-text-sec hover:bg-bg-elev disabled:opacity-50"
                  >
                    测试
                  </button>
                  <button
                    type="button"
                    onClick={() => void save(ch.channel, !ch.enabled)}
                    disabled={busy === ch.channel}
                    className={clsx(
                      'rounded px-2 py-1 text-xs transition disabled:opacity-50',
                      ch.enabled
                        ? 'border border-border-base text-text-sec hover:bg-bg-elev'
                        : 'bg-accent text-bg-base hover:opacity-90',
                    )}
                  >
                    {ch.enabled ? '停用' : '启用'}
                  </button>
                </div>
              </div>

              {ch.hint && <p className="mt-1.5 text-[11px] text-text-ter">{ch.hint}</p>}
              {ch.lastError && (
                <p className="mt-1 text-[11px] text-danger">最近错误:{ch.lastError}</p>
              )}
              {testResult[ch.channel] && (
                <p className="mt-1 text-[11px] text-text-sec">{testResult[ch.channel]}</p>
              )}

              {fields.length > 0 && (
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {fields.map((f) => (
                    <label key={f.key} className="space-y-1 text-[11px]">
                      <span className="text-text-ter">{f.label}</span>
                      <input
                        type={f.secret ? 'password' : 'text'}
                        value={draft[f.key] ?? ''}
                        onChange={(e) => setField(ch.channel, f.key, e.target.value)}
                        placeholder={ch.configured ? '留空则不修改' : '尚未配置'}
                        className="w-full rounded-md border border-border-base bg-bg-elev px-2 py-1.5 text-xs text-text-pri outline-none focus:border-accent"
                        autoComplete="off"
                      />
                    </label>
                  ))}
                  <div className="sm:col-span-2">
                    <button
                      type="button"
                      onClick={() => void save(ch.channel, ch.enabled)}
                      disabled={busy === ch.channel}
                      className="rounded border border-border-base px-2 py-1 text-xs text-text-sec hover:bg-bg-elev disabled:opacity-50"
                    >
                      保存凭据
                    </button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
