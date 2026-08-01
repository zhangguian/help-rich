import type { Config } from 'tailwindcss';

/**
 * Tailwind 配置(frontend-arch §16.2 + v0.4 Liquid Glass)
 *
 * 颜色全部映射到 CSS 变量(单主题纯黑 void,见 styles/tokens.css)
 */
const config: Config = {
  content: [
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Liquid Glass(v0.4-roadmap §3)
        'void': 'var(--void)',
        'glow-emerald': 'var(--glow-emerald)',
        'glow-cyan': 'var(--glow-cyan)',
        'glass-fill': 'var(--glass-fill)',
        // 主色调
        'bg-base': 'var(--bg-base)',
        'bg-surface': 'var(--bg-surface)',
        'bg-elevated': 'var(--bg-elevated)',
        'bg-subtle': 'var(--bg-subtle)',
        // 文字
        'text-pri': 'var(--text-primary)',
        'text-sec': 'var(--text-secondary)',
        'text-ter': 'var(--text-tertiary)',
        // 边框
        'border-def': 'var(--border-default)',
        'border-str': 'var(--border-strong)',
        // 强调
        'accent': 'var(--accent-primary)',
        'accent-hover': 'var(--accent-hover)',
        'accent-subtle': 'var(--accent-subtle)',
        // 涨跌色(中国惯例)
        'up': 'var(--status-up)',
        'up-bg': 'var(--status-up-bg)',
        'down': 'var(--status-down)',
        'down-bg': 'var(--status-down-bg)',
        'warn': 'var(--status-warn)',
        'warn-bg': 'var(--status-warn-bg)',
        'neutral': 'var(--status-neutral)',
      },
      fontFamily: {
        sans: ['var(--font-jakarta-sans)', 'PingFang SC', 'Microsoft YaHei', 'system-ui', 'sans-serif'],
        mono: ['var(--font-jetbrains-mono)', 'SF Mono', 'Consolas', 'monospace'],
      },
      borderRadius: {
        sm: '6px',
        md: '8px',
        lg: '12px',
        glass: 'var(--glass-radius)',
      },
      boxShadow: {
        glass: 'var(--glass-shadow)',
      },
      backdropBlur: {
        liquid: 'var(--blur-liquid)',
      },
    },
  },
  plugins: [],
};
export default config;