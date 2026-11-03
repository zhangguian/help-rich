'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import {
  dispatchPremarketBrief,
  fetchWorkflowSchedule,
  generateIntradayBrief,
  generatePremarketBrief,
  type WorkflowBrief,
  type WorkflowDelivery,
} from '@/lib/api/advanced';

interface WindowInfo {
  kind: string;
  at: string;
  hour: number;
  minute: number;
}

const KIND_LABEL: Record<string, string> = {
  premarket: '盘前简报',
  intraday_am: '盘中速览(午盘)',
  intraday_pm: '盘中速览(尾盘)',
  postmarket: '盘后复盘',
};

const KIND_HINT: Record<string, string> = {
  premarket: '隔夜消息 + 今日关注 + 持仓体检',
  intraday_am: '上午收盘快照',
  intraday_pm: '尾盘变动',
  postmarket: '交给复盘模块,这里不重复跑',
};

/**
 * 盘前简报 / 盘中速览(阶段4 三段式 Agent)
 *
 * 两条设计原则:
 *
 * 1. **生成和推送是两个按钮。** 推送真的会把消息发到手机上,不可撤回。
 *    合并成一个按钮就等于用户点一下就被打扰一次,所以"生成"(只看)在前,
 *    "推送"(真发)需要二次确认。
 *
 * 2. **明确告诉用户自动推送的前提条件。** 定时任务是后端进程内的循环,
 *    后端没启动就不会自动跑。与其让用户以为"配好了就一定会收到",
 *    不如在界面上直说。
 */
export function BriefPanel() {
  const [windows, setWindows] = useState<WindowInfo[]>([]);
  const [brief, setBrief] = useState<WorkflowBrief | null>(null);
  const [delivered, setDelivered] = useState<WorkflowDelivery[]>([]);
  const [loading, setLoading] = useState<'' | 'gen' | 'push' | 'intraday'>('');
  const [error, setError] = useState('');
  const [confirmPush, setConfirmPush] = useState(false);
  // 阶段10:下午档从 14:50 挪到了 14:00(与盘中复盘的档位一致)。
  // 14:50 仍保留 —— 那是旧的异动扫描窗口,后端仍接受。
  const [slot, setSlot] = useState<'11:30' | '14:00' | '14:50'>('11:30');

  useEffect(() => {
    void fetchWorkflowSchedule()
      .then((r) => setWindows(r.windows))
      .catch(() => setWindows([]));
  }, []);

  const runGenerate = useCallback(async () => {
    setLoading('gen');
    setError('');
    setDelivered([]);
    setConfirmPush(false);
    try {
      setBrief(await generatePremarketBrief());
    } catch (e) {
      setError(e instanceof Error ? e.message : '生成失败');
      setBrief(null);
    } finally {
      setLoading('');
    }
  }, []);

  const runIntraday = useCallback(async () => {
    setLoading('intraday');
    setError('');
    setDelivered([]);
    setConfirmPush(false);
    try {
      const r = await generateIntradayBrief(slot);
      setBrief(r);
      if (r.delivered?.length) setDelivered(r.delivered);
    } catch (e) {
      setError(e instanceof Error ? e.message : '生成失败');
      setBrief(null);
    } finally {
      setLoading('');
    }
  }, [slot]);

  const runPush = useCallback(async () => {
    setLoading('push');
    setError('');
    try {
      const r = await dispatchPremarketBrief();
      setDelivered(r.delivered);
      setConfirmPush(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : '推送失败');
    } finally {
      setLoading('');
    }
  }, []);

  const busy = loading !== '';

  return (
    <div className="space-y-4">
      {/* ---- 定时窗口 ---- */}
      <Card padding="lg" className="space-y-3">
        <header>
          <h2 className="text-base font-semibold">三段式简报</h2>
          <p className="mt-1 text-xs text-text-sec">
            到点自动生成并推送到你已启用的渠道;也可以随时手动触发。
          </p>
        </header>

        {windows.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2">
            {windows.map((w) => (
              <div
                key={w.kind}
                className="flex items-start gap-3 rounded-md border border-border-def bg-bg-elevated px-3 py-2"
              >
                <span className="font-mono text-sm text-accent">{w.at}</span>
                <div className="min-w-0">
                  <div className="text-xs font-medium text-text-pri">
                    {KIND_LABEL[w.kind] ?? w.kind}
                  </div>
                  <div className="text-[11px] text-text-ter">
                    {KIND_HINT[w.kind] ?? ''}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[11px] leading-relaxed text-warn">
          自动推送依赖后端进程常驻。后端没开着(比如电脑关机、服务停了),
          对应时段的简报不会补发 —— 这时手动点「生成并推送」即可。
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void runGenerate()}
            disabled={busy}
            className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-bg-base transition hover:opacity-90 disabled:opacity-50"
          >
            {loading === 'gen' ? '生成中…' : '生成盘前简报'}
          </button>

          <div className="flex items-center gap-1 rounded-md border border-border-def p-0.5">
            {(['11:30', '14:00', '14:50'] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSlot(s)}
                className={clsx(
                  'rounded px-2 py-1 text-xs transition',
                  slot === s
                    ? 'bg-bg-elevated text-text-pri'
                    : 'text-text-ter hover:text-text-sec',
                )}
              >
                {s}
              </button>
            ))}
            <button
              type="button"
              onClick={() => void runIntraday()}
              disabled={busy}
              className="rounded px-2 py-1 text-xs text-text-sec transition hover:text-text-pri disabled:opacity-50"
            >
              {loading === 'intraday' ? '生成中…' : '盘中速览'}
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}
      </Card>

      {/* ---- 简报内容 ---- */}
      {brief && (
        <Card padding="lg" className="space-y-3">
          <header className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold">{brief.title || '简报'}</h3>
            <span className="font-mono text-[11px] text-text-ter">{brief.kind}</span>
          </header>

          {brief.summary && (
            <p className="text-sm leading-relaxed text-text-pri">{brief.summary}</p>
          )}

          {brief.lines.length > 0 && (
            <ul className="space-y-1">
              {brief.lines.map((line, i) => (
                <li key={i} className="text-xs leading-relaxed text-text-sec">
                  · {line}
                </li>
              ))}
            </ul>
          )}

          {brief.stockCodes.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {brief.stockCodes.map((c) => (
                <span
                  key={c}
                  className="rounded border border-border-def bg-bg-elevated px-1.5 py-0.5 font-mono text-[11px] text-text-sec"
                >
                  {c}
                </span>
              ))}
            </div>
          )}

          {/* 推送:必须二次确认,因为真的会打扰到手机 */}
          <div className="border-t border-border-def pt-3">
            {confirmPush ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-text-sec">
                  确认推送到已启用的通知渠道?
                </span>
                <button
                  type="button"
                  onClick={() => void runPush()}
                  disabled={busy}
                  className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent transition hover:bg-accent/20 disabled:opacity-50"
                >
                  {loading === 'push' ? '推送中…' : '确认推送'}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmPush(false)}
                  disabled={busy}
                  className="rounded-md px-2 py-1.5 text-xs text-text-ter transition hover:text-text-sec"
                >
                  取消
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmPush(true)}
                disabled={busy}
                className="rounded-md border border-border-def px-3 py-1.5 text-xs text-text-sec transition hover:border-accent/50 hover:text-text-pri disabled:opacity-50"
              >
                推送这份简报
              </button>
            )}
          </div>

          {delivered.length > 0 && (
            <div className="space-y-1">
              {delivered.map((d) => (
                <div key={d.channel} className="text-[11px]">
                  <span
                    className={clsx(
                      'font-mono',
                      d.ok ? 'text-success' : 'text-danger',
                    )}
                  >
                    {d.channel}
                  </span>
                  <span className="ml-2 text-text-ter">
                    {d.ok ? '已送达' : (d.detail ?? '失败')}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      <p className="text-[11px] leading-relaxed text-text-ter">
        简报中的数字来自确定性计算(行情、资金流、持仓),AI 只负责组织语言,
        不参与任何数值计算。内容仅供自用记录,不构成投资建议。
      </p>
    </div>
  );
}
