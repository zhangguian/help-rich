"""数据源抽象(arch §5.5)"""
from abc import ABC, abstractmethod

from app.data.unified import UnifiedQuote


class DataSource(ABC):
    """数据源抽象,支持多源"""

    name: str  # "sina" / "tencent"

    @abstractmethod
    async def get_quote(self, code: str) -> UnifiedQuote:
        """获取单只实时行情。code 形如 '600519.SH' / '000001.SZ'"""

    @abstractmethod
    async def get_quotes(self, codes: list[str]) -> list[UnifiedQuote]:
        """批量获取。新浪/腾讯都支持一次请求多只,子类应复用单请求"""
