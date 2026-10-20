"""按业务域组织的模块(见 `docs/adr/ADR-0001-modules-domain-layout.md`)。

约定(由 `tests/test_architecture_boundaries.py` 强制):
- 一个域一个子包,内部分层:`api.py` / `service.py` / `repository.py` / `schemas.py`
- **跨域只能 import 对方的 `service`**,不得 import 对方的 `api` 或 `repository`
- 跨域共享的 ORM 表仍留在 `app/models/orm.py`,不按域拆分

迁移批次见 ADR 的「迁移顺序」表。
"""

__all__: list[str] = []
