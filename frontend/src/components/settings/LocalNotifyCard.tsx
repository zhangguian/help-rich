'use client';

import { useEffect, useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import { testPriceAlertPopup } from '@/lib/api/priceAlerts';
import {
  browserNotifyPermission,
  isAlertSoundEnabled,
  requestBrowserNotify,
  setAlertSoundEnabled,
  showBrowserNotification,
  type BrowserNotifyPermission,
} from '@/lib/alertNotify';
import { useUIStore } from '@/stores/useUIStore';

/**
 * 本机提醒设置(浏览器通知 + 应用内提示音)
 *
 * **为什么单独一张卡**:上面「通知渠道」配的是**后端**推的渠道
 * (桌面气泡 / 钉钉 / Bark …)。这一张配的是**浏览器这边**的:
 * - 浏览器系统通知:浏览器自带 package identity,`new Notification()`
 *   在 Win11 上能弹真正的通知中心卡片 —— 后端托盘气泡不渲染时的第二条路。
 * - 应用内提示音:配合应用内弹窗,用户不盯着屏幕也能听见。
 *
 * **绝不自动弹权限框**:浏览器通知必须由用户点一下才授权,
 * 所以这里只给按钮,不自动 `requestPermission()`。
 */
const PERMISSION_LABEL: Record<BrowserNotifyPermission, string> = {
  granted: '已授权',
  denied: '已拒绝(需在浏览器地址栏左侧的站点设置里恢复)',
  default: '未授权',
  unsupported: '当前环境不支持',
};

export function LocalNotifyCard() {
  const showToast = useUIStore((s) => s.showToast);
  const [permission, setPermission] = useState<BrowserNotifyPermission>('default');
  const [soundOn, setSoundOn] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setPermission(browserNotifyPermission());
    setSoundOn(isAlertSoundEnabled());
  }, []);

  const testPopup = async () => {
    setBusy(true);
    try {
      await testPriceAlertPopup();
      showToast({ type: 'info', message: '已发送一条模拟提醒,看右下角' });
    } catch (e) {
      showToast({
        type: 'error',
        message: e instanceof Error ? e.message : '自检失败',
      });
    } finally {
      setBusy(false);
    }
  };

  const request = async () => {
    setBusy(true);
    try {
      const p = await requestBrowserNotify();
      setPermission(p);
      showToast({
        type: p === 'granted' ? 'success' : 'warning',
        message:
          p === 'granted'
            ? '浏览器通知已开启'
            : `未开启:${PERMISSION_LABEL[p]}`,
      });
    } finally {
      setBusy(false);
    }
  };

  const testBrowserNotify = () => {
    showBrowserNotification('价格提醒 · 测试', '豫能控股 做T接回\n触发条件:价格 <= 8.771\n当前价:8.83');
    showToast({ type: 'info', message: '已发一条浏览器通知(没看到就是没授权)' });
  };

  const toggleSound = () => {
    const next = !soundOn;
    setSoundOn(next);
    setAlertSoundEnabled(next);
    showToast({ type: 'info', message: next ? '提示音已开启' : '提示音已关闭' });
  };

  return (
    <Card padding="lg" className="space-y-4">
      <header>
        <h2 className="text-base font-semibold">本机提醒</h2>
        <p className="mt-1 text-xs text-text-sec">
          这两项在**你的浏览器**里生效,和上面的「通知渠道」(后端推送)互相独立。
          应用内弹窗始终开着,不需要任何授权。
        </p>
      </header>

      <div className="space-y-3">
        <div className="rounded-md border border-border-def p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">应用内弹窗</span>
              <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent">
                始终开启
              </span>
            </div>
            <button
              type="button"
              onClick={() => void testPopup()}
              disabled={busy}
              className="rounded border border-border-def px-2 py-1 text-xs text-text-sec transition hover:bg-bg-elevated disabled:opacity-50"
            >
              试弹一次
            </button>
          </div>
          <p className="mt-1.5 text-[11px] text-text-ter">
            点一下会真的在右下角弹一条模拟提醒(不碰任何规则、不记流水)。
            没弹出来 → 应用没开着或页面在后台。
          </p>
        </div>

        <div className="rounded-md border border-border-def p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">浏览器系统通知</span>
              <span
                className={clsx(
                  'rounded px-1.5 py-0.5 text-[10px]',
                  permission === 'granted'
                    ? 'bg-accent/15 text-accent'
                    : 'bg-bg-elevated text-text-ter',
                )}
              >
                {PERMISSION_LABEL[permission]}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {permission === 'granted' && (
                <button
                  type="button"
                  onClick={testBrowserNotify}
                  className="rounded border border-border-def px-2 py-1 text-xs text-text-sec transition hover:bg-bg-elevated"
                >
                  测试
                </button>
              )}
              <button
                type="button"
                onClick={() => void request()}
                disabled={busy || permission === 'granted' || permission === 'unsupported'}
                className="rounded bg-accent px-2 py-1 text-xs text-bg-base transition hover:opacity-90 disabled:opacity-50"
              >
                开启
              </button>
            </div>
          </div>
          <p className="mt-1.5 text-[11px] text-text-ter">
            开启后即使应用在后台,提醒也会以系统通知卡片弹到右下角。
          </p>
        </div>

        <div className="rounded-md border border-border-def p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">应用内提示音</span>
              <span
                className={clsx(
                  'rounded px-1.5 py-0.5 text-[10px]',
                  soundOn ? 'bg-accent/15 text-accent' : 'bg-bg-elevated text-text-ter',
                )}
              >
                {soundOn ? '已开启' : '已关闭'}
              </span>
            </div>
            <button
              type="button"
              onClick={toggleSound}
              className={clsx(
                'rounded px-2 py-1 text-xs transition',
                soundOn
                  ? 'border border-border-def text-text-sec hover:bg-bg-elevated'
                  : 'bg-accent text-bg-base hover:opacity-90',
              )}
            >
              {soundOn ? '关闭' : '开启'}
            </button>
          </div>
          <p className="mt-1.5 text-[11px] text-text-ter">
            提醒触发时响两声,配合应用内弹窗,不用一直盯着屏幕。
          </p>
        </div>
      </div>
    </Card>
  );
}
