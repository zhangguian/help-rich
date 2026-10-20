# Task 12 Report — 改动 B-4 前端 screener 显示基本面状态

## Status

**DONE_WITH_CONCERNS** — 用户可见变化已落地，但 brief 与实际代码结构不一致，已采取最小偏离。

## 实现了什么

在 screener Top N 候选股卡片下方新增条件渲染：当 `pick.fundamental_filter_status` 为 `'passed'` 显示绿色「✓ 基本面通过」；为其他真值（包括 `'kicked'`）显示红色「⚠️ 基本面被过滤」；undefined/null 不渲染。

### JSX 插入点

`frontend/src/components/screener/ScreenerPanel.tsx` 第 400-408 行，紧跟 `triggeredRules` chips 块之后、`</div>` 闭合之前：

```tsx
{p.fundamental_filter_status && (
  <div className="text-xs mt-1">
    {p.fundamental_filter_status === 'passed' ? (
      <span className="text-up">✓ 基本面通过</span>
    ) : (
      <span className="text-down">⚠️ 基本面被过滤</span>
    )}
  </div>
)}
```

颜色沿用项目 Tailwind 主题色 `text-up` / `text-down`（在 35 个文件中已使用），emoji 按 brief 字面量。

## Concerns / Brief 与代码不一致之处

brief 同时存在两处内部矛盾，按字面执行会得不到任何用户可见变化：

### 1. 目标文件不对

brief 写「Modify ONLY `frontend/src/app/screener/page.tsx`」+「找 Top N 卡片渲染处（通常是 `.map(pick => ...)`）」。

但 `frontend/src/app/screener/page.tsx` 全文 14 行，只是一个把 `<ScreenerPanel />` 居中包一层的薄路由壳。Top N `.map((p) => ...)` 实际位于 `frontend/src/components/screener/ScreenerPanel.tsx`（同时被主页 tab 内嵌和 `/screener` 路由共用）。

如果坚持只改 `page.tsx`，将无法交付 brief 描述的用户可见变化。所以修改了 `ScreenerPanel.tsx`。

### 2. 类型文件不对

brief 写检查 `frontend/src/lib/types.ts` 是否含 `fundamental_filter_status`。

但 ScreenerPick 是 **手工定义** 的接口（`frontend/src/lib/screener.ts` 第 15-33 行），不在 `types.ts`（那是 openapi-typescript 生成器输出，不含 ScreenerPick）。`types.ts` 缺字段是预期的——ScreenerPick 类型从不在那里。

无需跑 `pnpm gen-types`，直接给 `ScreenerPick` 加上 `fundamental_filter_status?: 'passed' | 'kicked' | null`（值域与后端 `screener_service.py:820-822` 一致：literal `'passed'` / `'kicked'`，DB 中 NULL 表示旧 run）。

## Files Changed

| 文件 | 行 | 变更 |
|---|---|---|
| `frontend/src/components/screener/ScreenerPanel.tsx` | 第 400-408 行（追加 9 行 JSX） | 新增基本面过滤状态条件渲染 |
| `frontend/src/lib/screener.ts` | 第 32 行后（追加 2 行） | 给 `ScreenerPick` 增 `fundamental_filter_status?: 'passed' \| 'kicked' \| null` |

合计：2 files, 11 insertions(+)

### 已确认未触碰

- 22 个本地未提交改动 ✓ 全部保留（git status 中仍标记为 M/D）
- 新 Alembic 迁移 `backend/migrations/versions/k3f4g5h6i7j8_drop_kline_cache.py` ✓ 未跟踪未触碰

## Validation

```text
$ pnpm exec tsc --noEmit
(no output — exit 0, pass)

$ pnpm build
   ✓ Compiled successfully
   Skipping linting
   Checking validity of types ...
   ✓ Generating static pages (13/13)
   ├ ○ /screener                2.06 kB   120 kB
   ...
   (exit 0, pass)
```

- typecheck：✅ 通过
- build：✅ 通过（13/13 静态页生成成功）

## Commit

- **Hash**：`ccc87ca`
- **Subject**：`feat(screener-ui): Top N 卡片显示基本面过滤状态 (改动 B)`
- **Author/Date**：zhangguian 2026-09-23 22:24:21 +0800
- **Body**：无
- **Files in commit**：2 (ScreenerPanel.tsx + screener.ts)

## Self-Review

- ✓ 条件渲染 `&&` 守卫保留，undefined/null（旧 run）不渲染
- ✓ `passed` 分支 → 绿色 `text-up`；其他真值（`'kicked'`） → 红色 `text-down`，与 brief 一致
- ✓ JSX 位置在 metrics grid 之后、triggeredRules chips 之后、内容区 `</div>` 闭合之前——不与现有元素冲突
- ✓ emoji ✓ / ⚠️ 字面量与 brief 一致
- ✓ className `text-xs mt-1` 与 brief 默认值一致
- ✓ 不动现有 JSX（只插入 1 个新块）
- ✓ 后端类型（`'passed' | 'kicked' | None`）映射到 TS 字面量联合（含 `null`）以覆盖 undefined 旧数据
- ✓ 22 个未提交改动 + 1 个新迁移未触碰

## Issues / Concerns

1. **brief 内部矛盾**：目标文件与 JSX 位置描述不一致。已采取的最小偏离：改 `ScreenerPanel.tsx`（实际卡片位置）+ 改 `screener.ts`（实际类型位置）。建议后续 brief writer 用 grep 自查目标文件是否真的存在 `.map(pick => ...)`，以及检查类型定义来源（手工 vs 自动生成）。
2. **未运行 `pnpm gen-types`**：因为 ScreenerPick 不从 OpenAPI 生成，跳过该步骤是正确选择。