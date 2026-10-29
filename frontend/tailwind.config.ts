import type { Config } from 'tailwindcss';

/**
 * Tailwind 配置 — v0.5 Azure Workbench
 *
 * 颜色全部映射到 CSS 变量(单主题浅色,见 src/styles/tokens.css)。
 * 保留 v0.7 的结构改善:borderRadius / boxShadow 用 theme(而非 extend)整体覆盖,
 * 消除与 Tailwind 默认刻度的撞值(此前 rounded-lg=12px 与 rounded-xl=12px 同值)。
 */
const config: Config = {
  content: [
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    // 整体覆盖,非 extend — 避免与默认刻度撞值
    borderRadius: {
      none: '0',
      xs: 'var(--radius-xs)',
      sm: 'var(--radius-sm)',
      DEFAULT: 'var(--radius-sm)',
      md: 'var(--radius-md)',
      lg: 'var(--radius-lg)',
      xl: 'var(--radius-xl)',
      '2xl': 'calc(var(--radius-xl) + 4px)',
      '3xl': 'var(--glass-radius)',
      full: '9999px',
    },
    boxShadow: {
      none: 'none',
      card: 'var(--shadow-card)',
      pop: 'var(--shadow-pop)',
      sm: 'var(--shadow-sm)',
      DEFAULT: 'var(--shadow-sm)',
      md: 'var(--shadow-md)',
      lg: 'var(--shadow-lg)',
      xl: 'var(--shadow-lg)',
      '2xl': 'var(--shadow-lg)',
    },
    extend: {
      colors: {
        // 画布与分层表面
        'canvas': 'var(--canvas)',
        'bg-base': 'var(--bg-base)',
        'bg-surface': 'var(--surface)',
        'bg-elevated': 'var(--surface-2)',
        'bg-subtle': 'var(--surface-3)',
        'surface-2': 'rgb(var(--surface-2-rgb) / <alpha-value>)',
        'surface-3': 'rgb(var(--surface-3-rgb) / <alpha-value>)',
        // 文字(alpha 通道经 <alpha-value> 通配)
        'text-pri': 'rgb(var(--text-pri-rgb) / <alpha-value>)',
        'text-sec': 'rgb(var(--text-sec-rgb) / <alpha-value>)',
        'text-ter': 'rgb(var(--text-ter-rgb) / <alpha-value>)',
        // 边框
        'border-def': 'rgb(var(--border-def-rgb) / <alpha-value>)',
        'border-str': 'rgb(var(--border-str-rgb) / <alpha-value>)',
        // 交互强调
        'accent': 'rgb(var(--accent-rgb) / <alpha-value>)',
        'accent-hover': 'rgb(var(--accent-hover-rgb) / <alpha-value>)',
        'accent-subtle': 'var(--accent-subtle)',
        // 行情色(红涨绿跌)— 仅限价格/图表语境
        'up': 'rgb(var(--up-rgb) / <alpha-value>)',
        'up-bg': 'var(--status-up-bg)',
        'down': 'rgb(var(--down-rgb) / <alpha-value>)',
        'down-bg': 'var(--status-down-bg)',
        'warn': 'rgb(var(--warn-rgb) / <alpha-value>)',
        'warn-bg': 'var(--status-warn-bg)',
        'neutral': 'rgb(var(--neutral-rgb) / <alpha-value>)',
        // 滚动池(作战计划 v2)—— 紫色只用于「全市场池」这一个身份标识
        'pool': 'rgb(var(--pool-rgb) / <alpha-value>)',
        'pool-bg': 'rgb(var(--pool-rgb) / 0.12)',
        // 语义色 — 仅限 badge/toast/边框/错误态,与行情方向无关
        'danger': 'rgb(var(--up-rgb) / <alpha-value>)',
        'danger-bg': 'var(--status-up-bg)',
        'success': 'rgb(var(--down-rgb) / <alpha-value>)',
        'success-bg': 'var(--status-down-bg)',
        'info': 'rgb(var(--accent-rgb) / <alpha-value>)',
        'info-bg': 'var(--accent-subtle)',
      },
      fontFamily: {
        sans: ['var(--font-jakarta-sans)', 'PingFang SC', 'Microsoft YaHei', 'system-ui', 'sans-serif'],
        mono: ['var(--font-jetbrains-mono)', 'SF Mono', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
};
export default config;
