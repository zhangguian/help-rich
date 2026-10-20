import type { Metadata, Viewport } from 'next';
import localFont from 'next/font/local';

import './globals.css';
import '@/styles/tokens.css';
import { Toaster } from '@/components/ui/Toaster';
import ServiceWorkerRegistrar from '@/components/pwa/ServiceWorkerRegistrar';

const jakartaSans = localFont({
  src: [
    { path: './fonts/PlusJakartaSans-400.woff2', weight: '400' },
    { path: './fonts/PlusJakartaSans-500.woff2', weight: '500' },
    { path: './fonts/PlusJakartaSans-600.woff2', weight: '600' },
    { path: './fonts/PlusJakartaSans-700.woff2', weight: '700' },
  ],
  variable: '--font-jakarta-sans',
  display: 'swap',
});
const jetBrainsMono = localFont({
  src: [
    { path: './fonts/JetBrainsMono-400.woff2', weight: '400' },
    { path: './fonts/JetBrainsMono-500.woff2', weight: '500' },
    { path: './fonts/JetBrainsMono-600.woff2', weight: '600' },
    { path: './fonts/JetBrainsMono-700.woff2', weight: '700' },
  ],
  variable: '--font-jetbrains-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: '买股工具室',
  description: '个人股票投资辅助工具 — 本地 Web 工具',
  manifest: '/manifest.webmanifest',
  appleWebApp: {
    capable: true,
    title: '买股工具室',
    statusBarStyle: 'black-translucent',
  },
  icons: {
    icon: [
      { url: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
      { url: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
    ],
    apple: [{ url: '/icons/apple-touch-icon.png', sizes: '180x180' }],
  },
};

export const viewport: Viewport = {
  themeColor: '#0b0e14',
  width: 'device-width',
  initialScale: 1,
  // 独立 App 模式下禁用双指缩放,避免误触
  maximumScale: 5,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning className={`${jakartaSans.variable} ${jetBrainsMono.variable}`}>
      <head>
        {/* 主题首屏同步:必须在首次绘制前把 data-theme 写上,
            否则刷新时会先闪一下默认深色再跳到用户上次选的主题。
            (与 src/lib/theme.ts 的 localStorage key 保持一致) */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var t=localStorage.getItem('rich-theme');if(t==='light')document.documentElement.dataset.theme='light';}catch(e){}",
          }}
        />
      </head>
      <body className="font-sans antialiased bg-bg-base text-text-pri">
        {children}
        <Toaster />
        <ServiceWorkerRegistrar />
      </body>
    </html>
  );
}