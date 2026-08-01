"""行情服务测试(P3.5):缓存 + 主备降级(用 mock 数据源,不依赖网络)

覆盖:
- 缓存命中(第二次不请求数据源)
- 缓存过期(超 TTL 重新请求)
- 主源失败 → 备源接管
- 主备都失败 → 返回空/抛错
- 批量:部分命中缓存

说明:测试用 asyncio.run 包装(不依赖 pytest-asyncio 配置)。
"""
import asyncio
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.data.base import DataSource
from app.data.unified import UnifiedQuote
from app.services.quote_service import QuoteError, QuoteService


def _mk_quote(code: str, price: str = "10.00") -> UnifiedQuote:
    return UnifiedQuote(
        code=code,
        name=f"股票{code}",
        current_price=Decimal(price),
        prev_close=Decimal("9.50"),
        open=Decimal("9.60"),
        high=Decimal("10.20"),
        low=Decimal("9.40"),
        change=Decimal(price) - Decimal("9.50"),
        change_pct=5.0,
        volume=10000,
        amount=Decimal("100000"),
        timestamp=datetime.now(),
    )


class FakeSource(DataSource):
    """可配置行为的数据源:记录调用次数,可注入失败"""

    name = "fake"

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    async def get_quote(self, code: str) -> UnifiedQuote:
        quotes = await self.get_quotes([code])
        return quotes[0]

    async def get_quotes(self, codes: list[str]) -> list[UnifiedQuote]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("source down")
        return [_mk_quote(c) for c in codes]


def _run(coro):
    return asyncio.run(coro)


class TestCache:
    def test_second_call_uses_cache(self, tmp_path: Path):
        primary = FakeSource()
        svc = QuoteService(primary=primary, backup=FakeSource(), cache_dir=tmp_path)
        q1 = _run(svc.get_quote("600519.SH"))
        q2 = _run(svc.get_quote("600519.SH"))
        assert q1.code == "600519.SH"
        assert q2.code == "600519.SH"
        assert primary.calls == 1  # 第二次命中缓存

    def test_cache_expired_refetches(self, tmp_path: Path):
        primary = FakeSource()
        svc = QuoteService(primary=primary, backup=FakeSource(), cache_dir=tmp_path, ttl=0)
        _run(svc.get_quote("600519.SH"))
        _run(svc.get_quote("600519.SH"))
        assert primary.calls == 2  # ttl=0 每次过期

    def test_cache_dir_isolated(self, tmp_path: Path):
        """不同缓存目录互不影响"""
        primary = FakeSource()
        a = QuoteService(primary=primary, backup=FakeSource(), cache_dir=tmp_path / "a")
        b = QuoteService(primary=primary, backup=FakeSource(), cache_dir=tmp_path / "b")
        _run(a.get_quote("600519.SH"))
        # b 目录无缓存,应再次请求
        _run(b.get_quote("600519.SH"))
        assert primary.calls == 2


class TestFailover:
    def test_primary_fail_backup_takes_over(self, tmp_path: Path):
        primary = FakeSource(fail=True)
        backup = FakeSource()
        svc = QuoteService(primary=primary, backup=backup, cache_dir=tmp_path)
        q = _run(svc.get_quote("600519.SH"))
        assert q.code == "600519.SH"
        assert primary.calls == 1
        assert backup.calls == 1

    def test_all_fail_raises(self, tmp_path: Path):
        primary = FakeSource(fail=True)
        backup = FakeSource(fail=True)
        svc = QuoteService(primary=primary, backup=backup, cache_dir=tmp_path)
        with pytest.raises(QuoteError):
            _run(svc.get_quote("600519.SH"))

    def test_partial_quotes_empty_when_all_fail(self, tmp_path: Path):
        """批量时主备都失败,返回 [] 而不是抛错(前端降级)"""
        primary = FakeSource(fail=True)
        backup = FakeSource(fail=True)
        svc = QuoteService(primary=primary, backup=backup, cache_dir=tmp_path)
        result = _run(svc.get_quotes(["600519.SH", "000001.SZ"]))
        assert result == []


class TestBatch:
    def test_batch_mixed_cache_and_fetch(self, tmp_path: Path):
        primary = FakeSource()
        svc = QuoteService(primary=primary, backup=FakeSource(), cache_dir=tmp_path)
        _run(svc.get_quote("600519.SH"))  # 预热缓存
        primary.calls = 0
        result = _run(svc.get_quotes(["600519.SH", "000001.SZ"]))
        assert len(result) == 2
        assert primary.calls == 1  # 只请求了缺失的 000001.SZ

    def test_batch_codes_empty(self, tmp_path: Path):
        svc = QuoteService(primary=FakeSource(), backup=FakeSource(), cache_dir=tmp_path)
        assert _run(svc.get_quotes([])) == []
