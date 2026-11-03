'use client';

/**
 * 到价提醒 SSE 订阅
 *
 * **为什么要有这条流**:到价提醒原来只有「后端推系统通知」这一条路,
 * 而 Windows 托盘气泡在部分 Win11 机器上根本不渲染 —— 用户开着桌面通知
 * 却什么都收不到。这条流把「提醒响了」这件事直接送到网页里,
 * 应用内弹窗只要页面开着就一定看得见。
 *
 * **降级**:SSE 连不上 → 退回 REST 轮询触发流水(最近 N 分钟真的响了的),
 * 降级是**可逆的**(不 close 掉 EventSource,浏览器自己会重连)。
 *
 * ⚠️ URL 拼接坑:`NEXT_PUBLIC_API_URL` 的值**已经含 `/api`**
 * → 再拼 `/api/...` 会得到 `/api/api/...` → 404。与 useSignalStream 同一套路。
 */
import { useEffect } from 'react';

import { apiBaseUrl, snakeToCamel } from '@/lib/api';
import {
  playAlertSound,
  showBrowserNotification,
  unlockAlertSound,
} from '@/lib/alertNotify';
import type { PriceAlertFiredEvent, PriceAlertSnapshotEvent } from '@/lib/api/priceAlerts';

import { usePriceAlertStore } from '@/stores/usePriceAlertStore';

const SSE_URL = `${apiBaseUrl().replace(/\/api\/?$/, '')}/api/price-alerts/stream`;

/** 连续失败多少次后降级到 REST 轮询 */
const FAIL_THRESHOLD = 3;
/** 降级后的拉取间隔(ms) */
const DEGRADE_POLL_INTERVAL = 5000;

type RawPayload = {
  event?: string;
  kind?: string | null;
  trigger_id?: number | null;
  triggered_at?: string | null;
  alert?: unknown;
  channels?: unknown;
  items?: unknown;
};

function toFired(raw: RawPayload): PriceAlertFiredEvent | null {
  const camel = snakeToCamel(raw) as {
    event?: string;
    kind?: string | null;
    triggerId?: number | null;
    triggeredAt?: string | null;
    alert?: PriceAlertFiredEvent['alert'];
    channels?: PriceAlertFiredEvent['channels'];
  };
  if (!camel.alert || !camel.alert.stockCode) return null;
  return {
    event: 'price_alert_fired',
    kind: camel.kind ?? null,
    triggerId: camel.triggerId ?? null,
    triggeredAt: camel.triggeredAt ?? null,
    alert: camel.alert,
    channels: camel.channels ?? [],
  };
}

/**
 * 订阅到价提醒流。组件挂载即开始,卸载即断开。
 */
export function usePriceAlertStream(): void {
  const push = usePriceAlertStore((s) => s.push);
  const setConnected = usePriceAlertStore((s) => s.setConnected);

  useEffect(() => {
    let closed = false;
    let failCount = 0;
    let es: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    // 声音需要一次用户手势才能解锁
    unlockAlertSound();

    const stop = () => {
      closed = true;
      if (es) {
        es.close();
        es = null;
      }
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      setConnected(false);
    };

    /** 收到一次提醒:进弹窗队列 + 声音 + 系统通知(已授权时) */
    const deliver = (ev: PriceAlertFiredEvent) => {
      push(ev);
      playAlertSound();
      showBrowserNotification(ev.alert.title, ev.alert.body);
    };

    /** 降级:REST 拉最近触发流水 */
    const startPolling = () => {
      if (pollTimer) return;
      pollTimer = setInterval(async () => {
        if (closed) return;
        try {
          const res = await fetch(`${apiBaseUrl()}/price-alerts/recent-fired`, {
            headers: { Accept: 'application/json' },
          });
          if (!res.ok) return;
          const data = (await res.json()) as { items?: unknown[] };
          for (const raw of data.items ?? []) {
            const ev = toFired(raw as RawPayload);
            if (ev) deliver(ev);
          }
        } catch {
          /* 保留上一份;下一轮再试 */
        }
      }, DEGRADE_POLL_INTERVAL);
    };

    const start = () => {
      if (closed) return;
      try {
        es = new EventSource(SSE_URL);
      } catch {
        failCount += 1;
        if (failCount >= FAIL_THRESHOLD) startPolling();
        return;
      }
      es.onopen = () => {
        failCount = 0;
        setConnected(true);
      };
      es.onmessage = (e) => {
        let payload: RawPayload;
        try {
          payload = JSON.parse(e.data) as RawPayload;
        } catch {
          return; // 非 JSON(心跳等)→ 忽略
        }
        failCount = 0;
        // 收到帧 = SSE 正常 → 停掉降级轮询
        if (pollTimer) {
          clearInterval(pollTimer);
          pollTimer = null;
        }
        if (payload.event === 'price_alert_snapshot') {
          const snap = snakeToCamel(payload) as unknown as PriceAlertSnapshotEvent;
          for (const raw of snap.items ?? []) {
            const ev = toFired(raw as RawPayload);
            if (ev) deliver(ev);
          }
          return;
        }
        if (payload.event === 'price_alert_fired') {
          const ev = toFired(payload);
          if (ev) deliver(ev);
        }
      };
      es.onerror = () => {
        failCount += 1;
        if (failCount >= FAIL_THRESHOLD) {
          setConnected(false);
          startPolling();
          // ⚠️ 不要 close() 掉 es:EventSource 自己会重连,后端恢复后自动回切 SSE
        }
      };
    };

    start();

    return () => {
      stop();
    };
  }, [push, setConnected]);
}
