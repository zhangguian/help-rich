# 发布流程文档:买股工具室

**文档版本**:v1.0
**创建日期**:2026-08-01
**最后更新**:2026-08-01
**文档状态**:已通过评审,准备实施
**目标读者**:开发者(自用项目,实际就是用户本人)
**配套文档**:
- `project-book.md`(PM 项目书,Source of Truth,文档↔代码版本映射见文档头)
- `testing-strategy.md`(测试策略,发布前测试见 §6)
- `backend-architecture.md`(启动/升级见第 14 章)

---

## 1. 版本规则

- 格式:`v主.次.补丁`(语义化版本)
- `v0.1.x`:MVP 迭代(文档 v1.8 ↔ 代码 v0.1.0)
- **每次发布 = 文档版本 + 代码版本同时更新**,映射关系记在 `project-book.md` 文档头

| 版本 | 含义 | 示例 |
|---|---|---|
| v0.1.0 | MVP 首个可用版本 | 流水 + 计算器 + 诊断 |
| v0.1.1 | 修 bug,不加功能 | 热力图暗色对比度修复 |
| v0.2.0 | 新增模块 | 自选股监控 |

---

## 2. 发布前检查清单

- [ ] 全量测试通过(`pytest -q` + 前端 `npm run test`)
- [ ] 前端 `npm run typecheck` 零错误 + lint 零警告
- [ ] 迁移还原测试通过(导出→删库→导入一致)
- [ ] 数据准确性测试通过(至少每日级)
- [ ] 文档同步:本次改动涉及的功能,对应文档已更新到当前版本
- [ ] 人工冒烟:完整走一遍「录入 → 计算 → 诊断 → 止损设置 → 年度账单」
- [ ] 数据库备份已存在(`~/rich/backups/`)

---

## 3. 发布步骤

```
Step 1  确认第 2 节清单全绿
Step 2  更新版本号
         后端:pyproject/__init__ 版本号
         前端:package.json version
         文档:project-book.md 头部「文档版本 ↔ 代码版本映射」
Step 3  更新文档变更历史(追加本次版本号)
Step 4  运行完整测试(最后一次全量)
Step 5  启动验证
         cd backend && uv run uvicorn app.main:app --reload --port 8000
         cd frontend && npm run gen-types && npm run dev
         http://localhost:5173 走一遍冒烟用例
Step 6  导出一次完整 JSON 备份到 `~/rich/backups/pre-{version}.json`
Step 7  记录发布日志(版本号 + 改动摘要 + 测试结果)到 plans/release-notes.md
```

---

## 4. 回滚流程

| 场景 | 动作 |
|---|---|
| 后端代码回滚 | `git revert` 或还原文件 → 重启 uvicorn |
| 前端代码回滚 | 还原文件 → `npm run dev` 热更新 |
| 数据库 Schema 回滚 | `alembic downgrade -1`(Alembic 支持) |
| 数据损坏 | 恢复 `~/rich/backups/data-{date}.db` → 重启 |
| 上次可用版本 | 有 `pre-{version}.json` 可还原数据 |

> 数据库数据优先于代码:回滚代码不动数据库;只有 Schema 迁移失败才动数据库。

---

## 5. 升级路径(用户视角)

- 旧版本用户直接运行新版本启动脚本 → 启动时 `alembic upgrade head` 自动迁移(见 backend §6.4)
- 无需手动备份提示:MVP 启动前先跑一次导出(第 3 节 Step 6)

---

## 6. 发布日志模板

```markdown
## v0.1.1(2026-08-05)

**改动**:
- 修复:21 档热力图暗色模式对比度
- 文档:ui-ux-design.md v1.6 → 更新到 v1.7

**测试**:pytest 全量 45 passed;typecheck 0 error;迁移还原 ✓

**风险**:无
```

---

**文档结束。**
