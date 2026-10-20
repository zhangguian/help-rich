'use client';

import { useEffect } from 'react';

/**
 * 注册 Service Worker(阶段5 PWA)。
 *
 * 只在生产构建注册 —— 开发模式下 SW 会缓存住 HMR 资源,导致改代码不生效。
 */
export default function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (process.env.NODE_ENV !== 'production') return;
    if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return;

    const register = () => {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch((err) => {
        // 静默失败:SW 注册不了不该影响正常使用
        console.warn('[pwa] Service Worker 注册失败:', err);
      });
    };

    if (document.readyState === 'complete') {
      register();
    } else {
      window.addEventListener('load', register, { once: true });
    }

    return () => window.removeEventListener('load', register);
  }, []);

  return null;
}
