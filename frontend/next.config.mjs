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
};

export default nextConfig;
