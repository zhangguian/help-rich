# 开发日志(Dev Log)使用指南

> **目的**:把"实施过程"系统化记录,做到留痕、可追溯、可回放。

## 文件清单

| 文件 | 作用 | 何时写 |
|---|---|---|
| `README.md` | 本文件 | — |
| `decisions-index.md` | ADR 总索引 | 每次写 ADR 后追加一行 |
| `ADR-NNNN-xxx.md` | 单个架构决策记录 | 临时决策 / 重大调整时 |
| `phase-completion-log.md` | Phase 完成日志 | 每个 Phase 完成时 |
| `runbook.md` | 运维手册(启动 / 备份 / 应急) | 遇到新坑时追加 |

## 写日志的最低要求

**每个 Phase 完成后 5 分钟**,在 `phase-completion-log.md` 追加一行。

**遇到"和规划不符 / 需要临时调整"**,先写 ADR 再写代码。

## 与规划文档的关系

- **`plans/` 文档**:决策、范围、架构(Source of Truth)
- **`docs/dev-log/`**:实施过程日志("为什么这样写")

不要把临时决策写进 `plans/`,否则规划文档会被污染。

## 命名规范

- ADR 文件:`ADR-NNNN-简短描述.md`(NNNN 4 位序号,从 0001 起)
- 描述用 kebab-case(短横线分隔)