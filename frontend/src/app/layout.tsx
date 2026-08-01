import type { Metadata } from 'next';
import localFont from 'next/font/local';

import './globals.css';
import '@/styles/tokens.css';
import { Toaster } from '@/components/ui/Toaster';

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
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className={`${jakartaSans.variable} ${jetBrainsMono.variable} antialiased bg-bg-base text-text-pri`}>
        {children}
        <Toaster />
      </body>
    </html>
  );
}