"""买股工具室后端应用包。

`__version__` 是全项目版本的**唯一来源**:FastAPI 元数据、启动日志、
/api/admin/health 都从这里读取,避免 pyproject / main.py / docs 各自写一份
(历史上曾出现 0.1.0 / v0.2.0 / v0.4.2 / v2.7 四处漂移)。
"""

__version__ = "0.5.0"

__all__ = ["__version__"]
