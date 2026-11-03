'use client';

/**
 * 本机提醒 · 声音 + 浏览器原生通知
 *
 * **为什么需要这一层**:Windows 托盘气泡在部分 Win11 机器上**根本不渲染**
 * (实测 `ShowBalloonTip` 返回成功,但屏幕上什么都没有 —— 见 ADR-0007 补充)。
 * 所以「提醒必须被看见」这件事不能只押在系统通知上,应用内弹窗才是兜底。
 *
 * **浏览器原生通知**是第三条路:浏览器自己**有 package identity**,
 * `new Notification()` 在 Win11 上能弹真正的通知中心卡片。
 * 但必须由用户点一下授权 —— 所以这里只提供「请求授权」,绝不自动弹权限框。
 */

/** localStorage 键:应用内提示音是否开启 */
const SOUND_KEY = 'rich.price-alert.sound';

/** 提示音开关(默认关 —— 不该在用户没同意的情况下突然出声) */
export function isAlertSoundEnabled(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(SOUND_KEY) === '1';
  } catch {
    return false;
  }
}

export function setAlertSoundEnabled(on: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(SOUND_KEY, on ? '1' : '0');
  } catch {
    /* 隐私模式下 localStorage 可能不可写 —— 忽略即可,不影响主流程 */
  }
}

let audioCtx: AudioContext | null = null;

type AudioCtor = typeof AudioContext;

function ensureAudioCtx(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  const w = window as Window & { webkitAudioContext?: AudioCtor };
  const AC = window.AudioContext ?? w.webkitAudioContext;
  if (!AC) return null;
  if (!audioCtx) audioCtx = new AC();
  if (audioCtx.state === 'suspended') void audioCtx.resume();
  return audioCtx;
}

/**
 * 浏览器要求 AudioContext 必须在**用户手势**里启动 —— 页面刚打开时
 * 音频上下文是 suspended 的,直接播放没有声音。
 * 这里挂一次性手势监听把上下文解锁,解锁后所有播放都能用。
 */
export function unlockAlertSound(): void {
  if (typeof document === 'undefined') return;
  const unlock = () => {
    ensureAudioCtx();
    document.removeEventListener('pointerdown', unlock);
    document.removeEventListener('keydown', unlock);
  };
  document.addEventListener('pointerdown', unlock, { once: true });
  document.addEventListener('keydown', unlock, { once: true });
}

/** 播两声短促提示音(880Hz → 1175Hz)。失败静默 —— 声音只是锦上添花。 */
export function playAlertSound(): void {
  if (!isAlertSoundEnabled()) return;
  const ctx = ensureAudioCtx();
  if (!ctx) return;
  try {
    const now = ctx.currentTime;
    const beeps: Array<[number, number]> = [
      [880, 0],
      [1175, 0.18],
    ];
    beeps.forEach(([freq, delay]) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, now + delay);
      gain.gain.exponentialRampToValueAtTime(0.25, now + delay + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + delay + 0.16);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now + delay);
      osc.stop(now + delay + 0.18);
    });
  } catch {
    /* 音频不可用就安静跳过 */
  }
}

/** 浏览器通知权限: 'granted' | 'denied' | 'default' | 'unsupported' */
export type BrowserNotifyPermission = 'granted' | 'denied' | 'default' | 'unsupported';

export function browserNotifyPermission(): BrowserNotifyPermission {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported';
  return Notification.permission as BrowserNotifyPermission;
}

/**
 * 请求浏览器通知权限。
 * **必须由用户点击触发** —— 浏览器在无手势时会直接拒绝。
 */
export async function requestBrowserNotify(): Promise<BrowserNotifyPermission> {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported';
  try {
    const res = await Notification.requestPermission();
    return res as BrowserNotifyPermission;
  } catch {
    return 'denied';
  }
}

/** 已经授权时弹一条系统通知;没授权就静默跳过(应用内弹窗仍然会出)。 */
export function showBrowserNotification(title: string, body: string): void {
  if (browserNotifyPermission() !== 'granted') return;
  try {
    const n = new Notification(title, {
      body,
      tag: 'rich-price-alert',
      // 不自动消失:价格提醒错过就是错过
      requireInteraction: true,
    });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch {
    /* 某些环境下构造通知会抛(非 https 等)—— 忽略 */
  }
}
