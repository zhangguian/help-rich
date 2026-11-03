#!/usr/bin/env node
/**
 * Tailwind 类名门禁 —— 找出「拼错了色键名」的类。
 *
 * 为什么需要它：
 *   Tailwind 里类名写错（如 bg-bg-elev 实际键名是 bg-elevated）**不报错、不警告**，
 *   只是那条规则压根不会生成 → 样式静默丢失。暗色底上缺背景的卡片跟深色底几乎融在一起，
 *   截图都看不出来，往往要等很久才被当成「设计如此」。
 *
 * 做法：
 *   1. 用 tailwind CLI 以「配置里的 content globs」生成一份全量 CSS 作为基准；
 *   2. 扫描 src 下所有源文件里的类名 token；
 *   3. 凡是「配置里不存在」的类名一律报出来（非零退出码）。
 *
 * 用法：npm run check:classes
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(FRONTEND, 'src');

/** 只审计「颜色 / 边框 / 表面」这类依赖项目自定义 token 的 utility 前缀。
 *  其余（flex / grid / p-4 / text-sm…）走 Tailwind 默认刻度，不存在拼写歧义。 */
const COLOR_PREFIXES = [
  'bg-', 'text-', 'border-', 'ring-', 'fill-', 'stroke-', 'from-', 'to-', 'via-',
  'divide-', 'outline-', 'decoration-', 'accent-', 'caret-', 'shadow-', 'placeholder-',
];

const SKIP_FILES = new Set(['tailwind.config.ts', 'postcss.config.js']);

const TOKEN_RE = /[A-Za-z0-9_:\-\[\]\(\)\.\#\%\/]+/g;

/** Tailwind 选择器里的特殊字符要转义。 */
function cssEscape(name) {
  return name.replace(/[:/[\]().%#&!>+~@$*'"\\|]/g, (ch) => `\\${ch}`);
}

/** 去掉变体前缀（hover: / focus: / md: …），取基础 utility；任意值里的冒号要保留。 */
function variantRoot(token) {
  let depth = 0;
  let root = token;
  let cur = '';
  for (const ch of token) {
    if (ch === '[') depth += 1;
    else if (ch === ']') depth -= 1;
    if (ch === ':' && depth === 0) {
      root = cur;
      cur = '';
    } else {
      cur += ch;
    }
  }
  return root;
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === '.next') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(ts|tsx|css)$/.test(entry)) out.push(full);
  }
  return out;
}

/** 源码里的类名 token -> 出现位置 */
function collectTokens() {
  const hits = new Map();
  for (const file of walk(SRC)) {
    const rel = relative(FRONTEND, file).split(sep).join('/');
    if (SKIP_FILES.has(rel)) continue;
    const text = readFileSync(file, 'utf8');
    // 只取字符串字面量里的内容，避免把 TS 标识符当类名
    for (const lit of text.matchAll(/'([^'\n]*)'|"([^"\n]*)"|`([^`]*)`/g)) {
      const blob = lit[1] ?? lit[2] ?? lit[3] ?? '';
      for (const raw of blob.match(TOKEN_RE) ?? []) {
        if (!raw.includes('-')) continue;
        const root = variantRoot(raw);
        if (!COLOR_PREFIXES.some((p) => root.startsWith(p))) continue;
        if (!hits.has(raw)) hits.set(raw, new Set());
        hits.get(raw).add(rel);
      }
    }
  }
  return hits;
}

function buildCss() {
  const dir = mkdtempSync(join(tmpdir(), 'tw-class-check-'));
  const input = join(dir, 'input.css');
  const output = join(dir, 'out.css');
  writeFileSync(input, '@tailwind base;\n@tailwind components;\n@tailwind utilities;\n');
  // 直接调 Tailwind 的 JS 入口，不走 node_modules/.bin 下的 .cmd 包装
  // （Node 24 起不允许直接 spawn .cmd，且 .cmd 不会正确继承 cwd）。
  // cwd 必须是 frontend：Tailwind 的 content globs 是相对「当前工作目录」解析的。
  const cli = join(FRONTEND, 'node_modules', 'tailwindcss', 'lib', 'cli.js');
  execFileSync(
    process.execPath,
    [cli, '-i', input, '-o', output, '--minify'],
    { cwd: FRONTEND, stdio: 'pipe' },
  );
  return readFileSync(output, 'utf8');
}

/** CSS 里是否存在这个类。
 *  注意：Tailwind 写出来的是 `.text-text-ter\/40` —— 反斜杠 + 斜杠，
 *  正则里的 `\/` 只匹配斜杠、吃不掉那个反斜杠，所以这里用字面量查找而不是正则。 */
function hasClass(css, token) {
  const needle = `.${cssEscape(token)}`;
  let idx = css.indexOf(needle);
  while (idx !== -1) {
    const next = css[idx + needle.length];
    if (next === undefined || !/[A-Za-z0-9_-]/.test(next)) return true;
    idx = css.indexOf(needle, idx + 1);
  }
  return false;
}

function main() {
  const css = buildCss();
  const hits = collectTokens();
  const missing = [];

  for (const [token, files] of [...hits.entries()].sort()) {
    const base = variantRoot(token).split('/')[0];
    if (hasClass(css, token)) continue;
    missing.push({
      token,
      files: [...files],
      kind: hasClass(css, base) ? '变体未生成' : 'utility 不存在',
    });
  }

  const refs = [...hits.values()].reduce((n, s) => n + s.size, 0);
  const fileCount = new Set([...hits.values()].flatMap((s) => [...s])).size;
  console.log(`源码中的颜色类 token：${hits.size} 个（${refs} 处引用，分布在 ${fileCount} 个文件）`);
  console.log(`编译 CSS 中查不到：${missing.length} 个`);

  if (missing.length === 0) {
    console.log('✅ 没有死类名');
    return 0;
  }
  console.log('-'.repeat(72));
  for (const { token, files, kind } of missing) {
    const shown = files.slice(0, 3).join(', ') + (files.length > 3 ? ' …' : '');
    console.log(`${token.padEnd(36)} ${kind.padEnd(12)} ${shown}`);
  }
  console.log('\n❌ 存在死类名（Tailwind 不会为它们生成任何规则 → 样式静默丢失）');
  return 1;
}

process.exit(main());
