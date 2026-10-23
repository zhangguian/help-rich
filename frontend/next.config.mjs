/** @type {import('next').NextConfig} */
const nextConfig = {
  // v0.2.1:ESLint warnings are noisy; skip lint during build.
  // Type safety still comes from `tsc --noEmit`. IDE / pre-commit keep lint.
  eslint: {
    ignoreDuringBuilds: true,
  },

  // P4(阶段10):关掉 React 18 StrictMode —— **只影响 dev**,prod 行为完全不变。
  //
  // 为什么关:StrictMode 会在开发环境把 effect 跑两遍、组件渲染两遍。
  // 盯盘页有轮询 + 图表订阅,双跑会让每个接口发两次、每张图建两遍,
  // 开发时的卡顿会被放大到分不清是「真卡」还是「双跑」——
  // 这也是为什么性能基线必须在 prod build 下测。
  //
  // 代价(写在这里免得以后被当 bug 改回去):少了「effect 双跑」这一层
  // 暴露 bug 的保护,某些「清理没写干净」的问题只能在生产环境复现。
  // 所以**开发期要更依赖手动验证**,别把 StrictMode 当安全网。
  reactStrictMode: false,

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
