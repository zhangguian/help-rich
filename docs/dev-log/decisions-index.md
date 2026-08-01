# 决策索引(ADR Index)

> 所有 ADR(Architecture Decision Records)一览。新增 ADR 在本文件追加一行,状态变更也在这里更新。

| 编号 | 标题 | 状态 | 日期 | 决策摘要 |
|---|---|---|---|---|
| 0001 | 包管理用 uv 而非 venv | 已采纳 | 2026-08-01 | uv 装包快 + 锁版本;venv 是 fallback |
| 0002 | ProviderFactory 改 async + 返回 None | 已采纳 | 2026-08-01 | v2.1 Key UI 决策:缺 Key 时优雅降级 |
| 0003 | ORM Base 改为直接 import 避免循环导入 | 已采纳 | 2026-08-01 | P1.4 阶段发现:models/orm.py 通过 __init__.py 绕路 import 会导致 Base.metadata 为空,create_all 漏表 |

## 状态说明

- **提议中**:讨论中,未实施
- **已采纳**:正在使用
- **被否决**:有更好替代方案
- **已废弃**:之前用过,后来换了
- **被取代**:被新的 ADR 取代(列出新 ADR 编号)