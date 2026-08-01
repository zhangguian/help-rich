# ADR-0003: ORM Base 直接 import 避免循环导入

## 状态
已采纳(2026-08-01,P1.4 实施时发现)

## 背景

P1.4 实施时,后端启动报错:`no such table: llm_api_keys`,但 `main.py` 的 `lifespan` 已调用 `Base.metadata.create_all`。

排查发现:
- `app/models/orm.py` 定义 `class LlmApiKey(Base): ...`
- `Base` 定义在 `app/db.py`
- `orm.py` 用 `from app.db import Base`(看上去没问题)
- 但**实际 SQLAlchemy 看到的 `Base.metadata` 是空的**,因为 `app/models/__init__.py` 也有 Base 定义?或者 import 顺序问题?

## 根因

具体根因:**`app/models/orm.py` 在 `app/db.py` 之前被 Python 加载**。
- `llm_keys.py` API 端点 import `repositories.llm_keys_repo`
- repo import `models.orm.LlmApiKey`
- `models.orm` 在此时执行
- 此时 `app.db` 还没被加载完毕(因为有循环)
- 结果:`Base.metadata` 在 `create_all` 时是空的

## 决策

**统一规则**:所有 ORM model 文件直接 `from app.db import Base`,**绝不**通过 `app.models.__init__` 或其他中间模块绕一圈。

```python
# app/models/orm.py(v2.1 修复后)
from app.db import Base   # ✓ 直接 import

# 禁止的写法:
from app.models.base import Base  # ❌ 容易循环
```

## 后果

- ✅ `Base.metadata.create_all(engine)` 能发现所有表
- ✅ 单元测试时单独 import model 也安全
- ⚠️ 未来若加新 model,必须**直接** import Base

## 备选方案(被否决)

| 方案 | 否决理由 |
|---|---|
| 把 Base 移到 `app/models/base.py`,db.py 从 models 导入 | 依然有循环风险 |
| 用 `Base = declarative_base()` 在 model 文件内定义 | 多个 model 会有不同 Base,SQLAlchemy 无法关联 |
| 用 Alembic 迁移替代 create_all | Alembic 是 P2.1 才启用的,P1.4 阶段还没有 migration |

## 参考

- backend-arch §4.4 纯函数与 IO 函数分离
- backend-arch §6.4 Alembic 迁移策略