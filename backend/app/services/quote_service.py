"""行情服务:主备数据源降级 + 5 分钟缓存
主:新浪(实测公司网络可用)
备:腾讯(实测可用,东财/akshare 被公司网络限流,见 ADR-0005 / ADR-0006)

**两条取数路径,缓存口径不同**(2026-10-29 秒级盯盘改造):

- `get_quote` / `get_quotes`:走 300s JSONCache —— **研究/历史路径**(复盘、统计、
  估值…),同一只票短时间内反复问就吃缓存。
- `get_quotes_fresh`:**跳过缓存**直取数据源 —— **盯盘热路径**。5 分钟缓存会让盘中
  价格滞后到 5 分钟,盯盘必须走实时。

之所以不直接改默认 TTL:300s 缓存被多处业务依赖,改默认值会连带改掉历史口径
(见 ADR-0006 与 `plans/backend-architecture.md` §5.8 的"分层"约定)。
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
        """批量行情(逐只查缓存,缺失的走数据源)"""
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

    async def get_quotes_fresh(self, codes: list[str]) -> list[UnifiedQuote]:
        """热路径批量行情:**跳过 JSONCache**,直取数据源(主源失败自动切备源)。

        给秒级盯盘用(`services/quote_poller.py`):5 分钟缓存会让盘中价格滞后到
        5 分钟,盯盘必须每轮都真取。

        语义与 `get_quotes` 的差别只有"读不读缓存":
        - **部分成功照常返回**(缺哪只就是哪只没取到),由调用方决定要不要沿用旧值;
        - **主备都失败**(返回空)才抛 `QuoteError` —— 这才是"行情源整体不可用"。
        """
        if not codes:
            return []
        quotes = await self._fetch(list(codes))
        if not quotes:
            raise QuoteError(f"行情获取失败: {','.join(codes)}")
        return quotes

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


# ============================================================
# 进程级单例
# ============================================================
# 为什么放在 service 层而不是 api 层:
#   `modules/alert/scheduler.py` 也要用同一个实例(复用 httpx 连接池 + 缓存),
#   而 modules 内**不得 import app.api.***(架构守卫
#   `test_modules_do_not_import_legacy_layered_api`)。所以单例必须住在
#   services 层,api 与 modules 都从这里取。
_quote_service: QuoteService | None = None


def get_quote_service() -> QuoteService:
    """全局唯一的 QuoteService 实例(懒创建)。"""
    global _quote_service
    if _quote_service is None:
        _quote_service = QuoteService()
    return _quote_service
