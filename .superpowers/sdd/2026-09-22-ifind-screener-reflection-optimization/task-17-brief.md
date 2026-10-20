# Task 17 Brief: 改动 C-5 — ReflectionCard.tsx 接入消息面提示

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。已交付：
- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1-16 commits: `74d6448` → ... → `27f1411` → `b633f48`
- 改动 A + B完成（Tasks 1-12）
- 改动 C 后端完成（Tasks 13-16）
- **本任务做改动 C 用户可见变化 #3**：ReflectionCard 22:00 弹窗加消息面提示行

## Global Constraints

- 工作分支: `main`
- 验证命令: `cd frontend && pnpm typecheck && pnpm build`
- PowerShell `&&` NOT supported — 用 `;`
- **本地 22 个未提交改动 + 1 个 untracked Alembic migration** —— 不动这些
- ⚠️ **`frontend/src/lib/scriptsStream.ts` 是 modified 文件之一** —— **不动**
- ⚠️ **`frontend/src/lib/screener.ts` 是 Task 12 amend 修改的文件** —— **不动**
- 失败静默: 前端 fetch `/api/reflection-context` 失败时，**不打扰 22:00 弹窗体验** (try/catch 包裹，返 null)
- commit 中文 `feat(scope): 描述`

## Interfaces from Earlier Tasks

- Consumes:
  - `GET /api/reflection-context?date=YYYY-MM-DD` (Task 16) → 返 `{date, summary: {announcements_count, news_count, top_news_title, fetched_for[]}, fetched_for_count, fetched_for[]}`
  - `frontend/src/lib/api.ts` (已存在, 导 `apiGet<T)(url, config?)` 函数)
- Produces:
  - `frontend/src/lib/api/reflection-context.ts` (新)：`fetchReflectionContext(dateISO) → ReflectionContextResponse | null`
  - `frontend/src/components/reflection/ReflectionCard.tsx` (修改): 加 1 行消息面提示行

## Task Description

### Files
- Create: `frontend/src/lib/api/reflection-context.ts`
- Modify: `frontend/src/components/reflection/ReflectionCard.tsx`

### Steps

#### Step 1: 写 api client

新建 `frontend/src/lib/api/reflection-context.ts`：

```typescript
/** ReflectionCard 22:00 消息面提示 API client (改动 C, v2.7) */
import { apiGet } from '../api';

export interface ReflectionContextSummary {
  announcementsCount: number;
  newsCount: number;
  topNewsTitle: string;
  fetchedFor: string[];
}

export interface ReflectionContextResponse {
  date: string;
  summary: ReflectionContextSummary | null;
  fetchedForCount: number;
  fetchedFor: string[];
}

export async function fetchReflectionContext(
  dateISO: string,
): Promise<ReflectionContextResponse | null> {
  try {
    return await apiGet<ReflectionContextResponse>(
      `/reflection-context?date=${dateISO}`,
    );
  } catch {
    // 失败静黙: 不打扰 22:00 弹窗体验
    return null;
  }
}
```

**关键**:
- ⚠️ **import 路径**：`'../api'` 而**非** `'./api'`，因为新文件在 `lib/api/` 子目录，与 `lib/api.ts` 是 **父**-子关系。`frontend/src/lib/screener.ts` 在 `lib/` 平级所以用 `'./api'` (peer pattern 不能直接抄)
- **字段命名**: 后端 FastAPI `announcements_count` / `news_count` 在响应拦截器里 snake_to_camel 转换 → 前端 TypeScript interface 必须用 **`announcementsCount`** / **`newsCount`** (camelCase)。`fetched_for` → `fetchedFor` 同理
- **try/catch 包裹**: 任何 fetch 失败 (网络 / 5xx / 解析错) 返 null，不抛异常

#### Step 2: 改 ReflectionCard.tsx

读 `frontend/src/components/reflection/ReflectionCard.tsx` 当前状态（已知 84 行, 含 `useEffect` 内 dynamic import `@/lib/api` 调用 `/scripts?limit=100`）。

**改动**:
1. 在文件顶部 import 段追加：
   ```typescript
   import { fetchReflectionContext, ReflectionContextSummary } from '@/lib/api/reflection-context';
   ```

2. 在组件内 state 段追加：
   ```typescript
   const [contextSummary, setContextSummary] = useState<ReflectionContextSummary | null>(null);
   ```

3. 在 `useEffect` 内**第二个** dynamic import `import('@/lib/api')` 块**之前**（不是 setShow 之前，是 setShow 之前），追加独立的 dynamic import 拉 reflection context：
   ```typescript
   // 22:00 弹窗消息面提示行 (改动 C, v2.7) - 失败静黙
   import('@/lib/api/reflection-context').then(async ({ fetchReflectionContext }) => {
     const ctx = await fetchReflectionContext(todayKey());
     if (ctx?.summary) {
       setContextSummary(ctx.summary);
     }
   });
   ```

4. 在渲染处 (在已实现盈亏 `<span>¥{realizedPnl ?? '--'}</span>` **之后**, `<div className="mt-3 flex gap-2">` 按钮组**之前**) 追加新行：
   ```tsx
   {contextSummary && (contextSummary.newsCount > 0 || contextSummary.announcementsCount > 0) && (
     <div className="mt-2 text-xs text-text-sec">
       <span className="font-mono font-semibold">📰 今日</span>{' '}
       {contextSummary.announcementsCount} 条公告 / {contextSummary.newsCount} 条新闻
       {contextSummary.topNewsTitle && (
         <span className="block text-text-ter mt-1">「{contextSummary.topNewsTitle}」</span>
       )}
     </div>
   )}
   ```

**关键修正 brief plan literal bug**:
- ⚠️ **brief plan 在 useEffect 内有 dynamic import + setShow 之前**，但 brief 实际应**单独**拉 reflection context，不依赖 todayTrades 检查（即使今日无交易，消息面提示仍有意义，例如纯持仓票的 22:00 复盘）
- ⚠️ **brief plan 字段命名错误**：用了 `contextSummaries.news_count` 等 snake_case，但 axios 拦截器响应会转 camelCase。TypeScript interface 必须用 camelCase `contextSummary.newsCount`
- ⚠️ **brief plan 渲染条件**: `contextScripts.scripts_count > 0 || ...` —— 应该是 `contextSummary` (单数，不是 brief 笔误的复数)
- **不要新加链接** (如 `/replay-scripts`) — 这是 22:00 提示不是全量复盘入口；保持简洁让用户看顶部一句话摘要即可

#### Step 3: 跑 typecheck + build

```bash
cd frontend && pnpm typecheck && pnpm build
```

Expected: 全部通过 (TypeScript 编译错或 Next.js build 错都会 abort)

#### Step 4: Commit

```bash
git add frontend/src/lib/api/reflection-context.ts frontend/src/components/reflection/ReflectionCard.tsx
git commit -m "feat(reflection-card): 22:00 弹窗加消息面提示行, 失败静黙 (改动 C)"
```

## Acceptance Criteria

- `frontend/src/lib/api/reflection-context.ts` 存在, 含 `fetchReflectionContext` + `ReflectionContextSummary` + `ReflectionContextResponse` interface
- `import { apiGet } from '../api'` (父-子路径)
- `fetchReflectionContext` try/catch 包裹, 失败返 null
- `ReflectionCard.tsx` 加 1 import + 1 state + 1 dynamic import + 1 render 行
- **不动** `frontend/src/lib/scriptsStream.ts` 或 `screener.ts`
- `pnpm typecheck && pnpm build` 全部通过
- 1 commit on main 仅含 2 个文件
- 22 个 modified 文件 (含 `frontend/src/lib/scriptsStream.ts`) + 1 untracked Alembic migration 未触碰

## Ambiguity Resolution

- **brief plan 有 4 个 bugs**：implementer 应该识别并修正：
  1. import 路径 (`./api` → `../api`)
  2. setShow 之前触发 (应单独触发, 不依赖 todayTrades)
  3. 字段命名 (snake_case → camelCase)
  4. 变量名 (contextScripts/something → contextSummary/something)
- **state 命名**: brief 用 `contextSummaries` (复数), implementer 改用 `contextSummary` (单数) 更准确 (只存一个 summary,不是列表)
- **不引 Link 到 `/replay-scripts`**: 这条弹窗只显示顶部摘要,不做导航 (留作后续 plan 范畴)
- **不重构 useEffect**: 只**追加**新 useEffect-style dynamic import,不改 setShow 触发条件
- **`apiGet` 是 default axios 拦截器**: 字段 snake_case → camelCase 是自动的, TypeScript interface 用 camelCase
- **pnpm vs npm**: 项目用 pnpm (注意 `pnpm` vs `pnpm`, 速看是 `p` 前缀), 按 brief 字面命令跑

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-17-report.md`

报告应包含：
- 实现了什么
- typecheck + build 输出
- 文件变更列表
- Commit hash + 短 subject
- **关键**: paste `git show --stat HEAD` + `git diff HEAD~1..HEAD -- frontend/src/components/reflection/ReflectionCard.tsx` 头部
- self-review 发现 (尤其 4 个 brief bug 修正)
- 任何 issues 或 concern