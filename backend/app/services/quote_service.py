"""行情服务:主备数据源降级 + 5 分钟缓存

主:新浪(实测公司网络可用)
备:腾讯(实测可用,东财/akshare 被公司网络限流,见 ADR-0005)
"""
import asyncio
import logging
from pathlib import Path

from app.data.base import DataSource
from app.data.cache import JSONCache
from app.data.sina import SinaClient
from app.data.tencent import TencentClient
from app.data.unified import UnifiedQuote

logger = logging.getLogger("app.data.quote_service")

QUOTE_TTL = 300  # 5 分钟


class QuoteService:
    """统一行情入口:缓存 → 主源 → 备源,全部失败抛 QuoteError"""

    def __init__(
        self,
        primary: DataSource | None = None,
        backup: DataSource | None = None,
        cache_dir: Path | None = None,
        ttl: int = QUOTE_TTL,
    ) -> None:
        self.primary = primary or SinaClient()
        self.backup = backup or TencentClient()
        self.cache = JSONCache(cache_dir)
        self.ttl = ttl

    async def get_quote(self, code: str) -> UnifiedQuote:
        """单只行情(带缓存)。失败抛 QuoteError"""
        key = f"quote:{code}"
        cached = self.cache.get(key, self.ttl)
        if cached:
            return UnifiedQuote.model_validate(cached)

        quote = await self._fetch([code])
        if not quote:
            raise QuoteError(f"行情获取失败: {code}")
        q = quote[0]
        self.cache.set(key, q.model_dump(mode="json"))
        return q

    async def get_quotes(self, codes: list[str]) -> list[UnifiedQuote]:
        """批量行情:逐只查缓存,缺失的走数据源"""
        keys = {c: f"quote:{c}" for c in codes}
        cached = {c: self.cache.get(k, self.ttl) for c, k in keys.items()}
        fresh: dict[str, UnifiedQuote] = {
            c: UnifiedQuote.model_validate(v) for c, v in cached.items() if v
        }
        missing = [c for c in codes if c not in fresh]
        if missing:
            for q in await self._fetch(missing):
                self.cache.set(f"quote:{q.code}", q.model_dump(mode="json"))
                fresh[q.code] = q
        return [fresh[c] for c in codes if c in fresh]

    async def _fetch(self, codes: list[str]) -> list[UnifiedQuote]:
        """主源失败 → 备源。主备都失败返回 []"""
        for source in (self.primary, self.backup):
            try:
                result = await asyncio.wait_for(source.get_quotes(codes), timeout=10)
                if result:
                    return result
            except asyncio.TimeoutError:
                logger.warning("[%s] timeout codes=%s", source.name, codes)
            except Exception as e:
                logger.warning("[%s] failed codes=%s err=%s", source.name, codes, e)
        return []


class QuoteError(Exception):
    """行情不可用(前端降级为骨架屏/缓存数据)"""
