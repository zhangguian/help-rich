# Task 12 Brief: 改动 B-4 — 前端 screener page 显示基本面状态 ⭐用户可见变化 #2⭐

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。已交付：
- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1-11 commits: `74d6448` → `84cba33` → `c8f9a0d` → `3be76ad` → `e493ee2` → `99a037a` → `7888122` → `dc24c10` → `e128eb7` → `69e9f6e`（Task 11 amended）
- 改动 A + 改动 B 后端都跑通了
- **本任务是改动 B 的最后一棒：用户能感知的 Top N 卡片显示基本面状态**

## Global Constraints

- 工作分支: `main`
- 前端栈: Next.js 14.2 App Router + React 18 + TS 5 + Tailwind 3.4 + Zustand 5 + Zod 4 + axios
- 颜色约定: `text-up`（涨/正）/ `text-down`（跌/负）Tailwind 主题色
- 前端构建: `cd frontend && pnpm typecheck && pnpm build`
- **本地 22 个未提交改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py`** —— 不动这些
- **本任务**只改 `frontend/src/app/screener/page.tsx` 1 个文件

## Interfaces from Earlier Tasks

- Consumes:
  - `ScreenerPick.fundamental_filter_status` 字段（'passed'/'kicked'/undefined）
  - **TypeScript 类型**（由 `frontend/src/lib/types.ts` 自动生成 from OpenAPI；如缺字段需先 `pnpm gen-types`）
- Produces:
  - Top N 卡片新增 1 行 UI：`fundamental_filter_status === 'passed'` 显示 "✓ 基本面通过"（绿色），否则显示 "⚠️ 基本面被过滤"（红色）；undefined 时不渲染

## Task Description

### Files
- Modify: `frontend/src/app/screener/page.tsx`（1 处 JSX 追加 + 可能的 className 微调）

### Steps

#### Step 1: 读 screener page.tsx

读 `frontend/src/app/screener/page.tsx`，找 Top N 卡片渲染处（通常是 `.map(pick => ...)` 或类似循环）。

**关键检查**：
- `pick` 对象的字段类型是否有 `fundamental_filter_status` 字段？
  - 如果**没有**：implementer 报告"types 缺字段"，跑 `cd frontend && pnpm gen-types` 重新生成
- `text-up` / `text-down` 类是否在 globals.css 或 tailwind.config 中定义？
- 卡片渲染里**其他字段**位置（选一个不冲突的插入点）

#### Step 2: 加状态字段

在 Top N 卡片渲染处，**插入**（不删改现有 JSX）：

```tsx
{pick.fundamental_filter_status && (
  <div className="text-xs mt-1">
    {pick.fundamental_filter_status === 'passed' ? (
      <span className="text-up">✓ 基本面通过</span>
    ) : (
      <span className="text-down">⚠️ 基本面被过滤</span>
    )}
  </div>
)}
```

**插入位置**：找一个不影响其他字段显示的位置（一般是其他 metrics 之后、底部 actions 之前）。

#### Step 3: 跑前端 typecheck

```bash
cd frontend && pnpm typecheck
```

Expected: 通过。如果 type 报错（fundamental_filter_status 字段不在 TS 类型里），先跑 `pnpm gen-types` 重生成。

#### Step 4: 跑前端 build

```bash
cd frontend && pnpm build
```

Expected: 成功

#### Step 5: Commit

```bash
git add frontend/src/app/screener/page.tsx
git commit -m "feat(screener-ui): Top N 卡片显示基本面过滤状态 (改动 B)"
```

## Acceptance Criteria

- `frontend/src/app/screener/page.tsx` Top N 卡片渲染新增 1 行条件渲染
- `pnpm typecheck` 通过
- `pnpm build` 通过
- 1 commit on main，仅含 1 个前端文件
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰
- **第 2 个用户可见变化**落地（screener Top N 卡片显示基本面状态）

## Ambiguity Resolution

- **`pick.fundamental_filter_status` 可能 undefined**（pre-改动 B 数据）—— 条件渲染 `{pick.fundamental_filter_status && ...}` 必须保留
- **"基本面被过滤"和"基本面通过"颜色**：brief 用 `text-up` / `text-down`，implementer 必须沿用项目 Tailwind 主题色（不要自己发明 className）
- **emoji** ✓ / ⚠️ 直接用 brief 字面
- **className `text-xs mt-1`** 是 brief 默认值 —— implementer 可以按页面风格微调间距
- **不动现有 JSX**（只插入 1 个新块）

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-12-report.md`

报告应包含：
- 实现了什么（具体插入点 + JSX 代码）
- 跑过的命令 + 结果（typecheck + build）
- 文件变更列表
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concerns