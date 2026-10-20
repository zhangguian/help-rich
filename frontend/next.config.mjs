/** @type {import('next').NextConfig} */
const nextConfig = {
  // v0.2.1:ESLint warnings are noisy; skip lint during build.
  // Type safety still comes from `tsc --noEmit`. IDE / pre-commit keep lint.
  eslint: {
    ignoreDuringBuilds: true,
  },

  // v0.7: disable the dev overlay indicator (compile / route badge).
  // It rewrites DOM on every HMR update, causing needless re-layout cost.
  // Next 14 only accepts an object here, so opt out per-position explicitly.
  devIndicators: {
    buildActivity: false,
    buildActivityPosition: 'bottom-right',
  },

  // 阶段5 PWA:Service Worker 与 manifest 必须允许被读取,
  // 且不能被 Next 的静态资源指纹逻辑改写(否则 sw.js 拿到旧哈希资源)。
  async headers() {
    return [
      {
        source: '/sw.js',
        headers: [
          { key: 'Cache-Control', value: 'public, max-age=0, must-revalidate' },
          { key: 'Service-Worker-Allowed', value: '/' },
        ],
      },
      {
        source: '/manifest.webmanifest',
        headers: [{ key: 'Content-Type', value: 'application/manifest+json' }],
      },
      {
        source: '/icons/:path*',
        headers: [{ key: 'Cache-Control', value: 'public, max-age=31536000, immutable' }],
      },
    ];
  },
};

export default nextConfig;
