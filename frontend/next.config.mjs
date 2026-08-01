/** @type {import('next').NextConfig} */
const nextConfig = {
  // v0.2.1:ESLint 警告太多,build 时跳过 lint(类型检查仍走 tsc --noEmit)
  // 保留 IDE / pre-commit 内的 lint 能力,生产前清理
  eslint: {
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;