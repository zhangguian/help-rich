"""秒级盯盘链路测试(2026-10-29 ADR-0006)

覆盖三处新行为:

1. `QuoteService.get_quotes_fresh` —— **跳过 5 分钟缓存**直取数据源;
   主源失败自动切备源;主备都失败抛 `QuoteError`。
   (研究路径 `get_quotes` 的 300s 缓存行为**不能变**。)
2. `services/quote_poller.py` —— 常驻轮询器:节拍、失败退避、空闲降频、
   快照写入与 stale 标记、交易时段门禁。
3. `GET /api/quotes/stream` —— SSE 端点:首帧快照 + 增量推送 + 代码过滤。

全部用 fake 数据源,**不打桩网络**。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.data.base import DataSource
from app.data.unified import UnifiedQuote
from app.main import app
from app.services.event_bus import event_bus
from app.services.quote_poller import (
    BACKOFF_LADDER,
    EVENT_QUOTE_SNAPSHOT,
    EVENT_QUOTE_UPDATE,
    QuotePoller,
)
from app.services.quote_service import QuoteError, QuoteService


# ============================================================
# fake 数据源
# ============================================================


def _mk_quote(code: str, price: str = "10.00", prev: str = "9.50") -> UnifiedQuote:
    p, pc = Decimal(price), Decimal(prev)
    return UnifiedQuote(
        code=code,
        name=f"测试{code}",
        current_price=p,
        prev_close=pc,
        open=pc,
        high=p,
        low=pc,
        change=p - pc,
        change_pct=float((p / pc - 1) * 100),
        volume=10000,
        amount=Decimal("100000"),
        timestamp=datetime.now(),
    )


class FakeSource(DataSource):
    """可控的数据源:记录调用次数,可配置抛错"""

    def __init__(self, name: str, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.calls: list[list[str]] = []

    async def get_quote(self, code: str) -> UnifiedQuote:
        return _mk_quote(code)

    async def get_quotes(self, codes: list[str]) -> list[UnifiedQuote]:
        self.calls.append(list(codes))
        if self.fail:
            raise RuntimeError(f"{self.name} 不可用")
        return [_mk_quote(c) for c in codes]


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "cache"


# ============================================================
# 1. 缓存分层
# ============================================================


class TestQuoteServiceFreshPath:
    async def test_fresh_skips_cache(self, cache_dir):
        """get_quotes_fresh 不读 5 分钟缓存 → 每次都真取"""
        primary = FakeSource("sina")
        svc = QuoteService(primary=primary, backup=FakeSource("tencent"), cache_dir=cache_dir)

        await svc.get_quotes_fresh(["600519.SH"])
        await svc.get_quotes_fresh(["600519.SH"])

        assert len(primary.calls) == 2, "热路径必须每次都打数据源"

    async def test_cached_path_uses_cache(self, cache_dir):
        """get_quotes(研究路径)仍然吃 300s 缓存 → 只取一次"""
        primary = FakeSource("sina")
        svc = QuoteService(primary=primary, backup=FakeSource("tencent"), cache_dir=cache_dir)

        await svc.get_quotes(["600519.SH"])
        await svc.get_quotes(["600519.SH"])

        assert len(primary.calls) == 1, "研究路径的缓存行为不能被改动"

    async def test_fresh_falls_back_to_backup(self, cache_dir):
        """主源失败 → 自动切备源"""
        primary = FakeSource("sina", fail=True)
        backup = FakeSource("tencent")
        svc = QuoteService(primary=primary, backup=backup, cache_dir=cache_dir)

        quotes = await svc.get_quotes_fresh(["600519.SH"])

        assert len(quotes) == 1
        assert quotes[0].code == "600519.SH"
        assert len(backup.calls) == 1

    async def test_fresh_raises_when_both_fail(self, cache_dir):
        """主备都失败 → 抛 QuoteError(不返回空列表冒充"没有行情")"""
        svc = QuoteService(
            primary=FakeSource("sina", fail=True),
            backup=FakeSource("tencent", fail=True),
            cache_dir=cache_dir,
        )
        with pytest.raises(QuoteError):
            await svc.get_quotes_fresh(["600519.SH"])

    async def test_fresh_empty_codes_returns_empty(self, cache_dir):
        """空列表直接返回空,不触网"""
        primary = FakeSource("sina")
        svc = QuoteService(primary=primary, backup=FakeSource("tencent"), cache_dir=cache_dir)

        assert await svc.get_quotes_fresh([]) == []
        assert primary.calls == []


# ============================================================
# 2. 轮询器
# ============================================================


class TestQuotePoller:
    async def test_poll_once_updates_snapshot(self):
        """成功一轮 → 快照写入 + stale=False + 广播事件"""
        primary = FakeSource("sina")
        poller = QuotePoller(
            quote_service=QuoteService(primary=primary, backup=FakeSource("tencent")),
            codes_provider=lambda: ["600519.SH"],
        )
        received: list[dict] = []
        unsub = event_bus.subscribe_callback(lambda m: _collect(received, m))

        await poller.poll_once()

        assert poller.snapshot.stale is False
        assert set(poller.snapshot.quotes) == {"600519.SH"}
        assert poller.snapshot.source == "sina"
        assert poller.snapshot.updated_at is not None
        # 广播已发出(事件是 create_task 异步触发,给一点时间)
        await asyncio.sleep(0.05)
        assert any(m.get("event") == EVENT_QUOTE_UPDATE for m in received)
        await unsub()

    async def test_failure_marks_stale_and_keeps_previous(self):
        """失败一轮 → 标 stale + 保留上一轮快照(不编造价格)"""
        primary = FakeSource("sina")
        backup = FakeSource("tencent")
        svc = QuoteService(primary=primary, backup=backup)
        poller = QuotePoller(quote_service=svc, codes_provider=lambda: ["600519.SH"])

        await poller.poll_once()
        good_price = poller.snapshot.quotes["600519.SH"].current_price

        # 两个源都挂
        primary.fail = True
        backup.fail = True
        await poller.poll_once()

        assert poller.snapshot.stale is True
        assert poller.snapshot.last_error is not None
        # 旧值仍在,且**没有被改写**
        assert poller.snapshot.quotes["600519.SH"].current_price == good_price

    async def test_no_codes_clears_snapshot(self):
        """watchlist 为空 → 清空快照并标 stale(不留旧价格装作新鲜)"""
        svc = QuoteService(primary=FakeSource("sina"), backup=FakeSource("tencent"))
        poller = QuotePoller(quote_service=svc, codes_provider=lambda: ["600519.SH"])
        await poller.poll_once()
        assert poller.snapshot.quotes

        poller._codes_provider = lambda: []
        await poller.poll_once()

        assert poller.snapshot.quotes == {}
        assert poller.snapshot.stale is True

    def test_backoff_ladder_after_failures(self):
        """连续失败 → 退避阶梯;上限封顶"""
        poller = QuotePoller(
            quote_service=QuoteService(primary=FakeSource("sina"), backup=FakeSource("tencent")),
            codes_provider=lambda: [],
        )
        assert poller._next_delay() == poller.idle_interval_sec, "无人订阅时走空闲档"

        poller._fail_streak = 1
        assert poller._next_delay() == BACKOFF_LADDER[0]
        poller._fail_streak = 3
        assert poller._next_delay() == BACKOFF_LADDER[2]
        poller._fail_streak = 99
        assert poller._next_delay() == BACKOFF_LADDER[-1], "退避必须封顶"

    def test_rest_access_keeps_high_frequency(self):
        """REST 命中 → 即使没有 SSE 订阅也保持 2s 高频"""
        poller = QuotePoller(codes_provider=lambda: [])
        assert poller._next_delay() == poller.idle_interval_sec

        poller.note_rest_access()
        assert poller._next_delay() == poller.interval_sec

    async def test_run_skips_outside_trading_time(self, monkeypatch):
        """非交易时段 → 不拉行情(省出口配额)"""
        calls: list[list[str]] = []

        class CountingSource(FakeSource):
            async def get_quotes(self, codes):
                calls.append(list(codes))
                return [_mk_quote(c) for c in codes]

        svc = QuoteService(primary=CountingSource("sina"), backup=FakeSource("tencent"))
        poller = QuotePoller(quote_service=svc, codes_provider=lambda: ["600519.SH"])

        monkeypatch.setattr("app.services.quote_poller.is_trading_time", lambda: False)

        # 只跑一轮:用 stop() 事件收工,不去 monkeypatch 全局 asyncio.sleep
        task = asyncio.create_task(poller.run())
        await asyncio.sleep(0.05)
        poller.stop()
        await asyncio.wait_for(task, timeout=2)

        assert calls == [], "非交易时段不该打数据源"


async def _collect(bucket: list[dict], msg: dict) -> None:
    bucket.append(msg)


# ============================================================
# 3. SSE 端点
# ============================================================


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class TestQuotesStreamEndpoint:
    def test_route_registered(self):
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/quotes/stream" in paths

    def test_route_order_beats_code_route(self):
        """`/quotes/stream` 必须注册在 `/quotes/{code}` 之前

        FastAPI 按注册顺序匹配:顺序反了 "stream" 会被 {code} 吃掉 → 422。
        """
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert paths.index("/api/quotes/stream") < paths.index("/api/quotes/{code}")

    async def test_first_frame_is_snapshot(self):
        """首帧 = 当前快照(带 stale 标记),不是空"""
        from app.api.quotes import quotes_stream

        resp = await quotes_stream(codes=None)
        gen = resp.body_iterator
        try:
            first = await gen.__anext__()
        finally:
            await gen.aclose()

        assert first.startswith("data: ")
        payload = json.loads(first.removeprefix("data: ").strip())
        assert payload["event"] == EVENT_QUOTE_SNAPSHOT
        assert "quotes" in payload
        assert "stale" in payload
        assert "updated_at" in payload

    async def test_update_event_pushed_with_filter(self):
        """轮询器广播 → SSE 收到增量帧;?codes= 过滤生效

        直接调端点协程(不走 TestClient 的同步流):SSE 是**无限**流,
        同步客户端关不干净会挂住测试进程。
        """
        from app.api.quotes import quotes_stream

        resp = await quotes_stream(codes="600519.SH")
        gen = resp.body_iterator
        try:
            await gen.__anext__()  # 首帧(快照)

            await event_bus.publish(
                {
                    "event": EVENT_QUOTE_UPDATE,
                    "quotes": [
                        {"code": "600519.SH", "current_price": "10.00"},
                        {"code": "000001.SZ", "current_price": "11.00"},
                    ],
                    "updated_at": None,
                    "stale": False,
                    "source": "sina",
                }
            )

            payload = None
            for _ in range(10):
                await asyncio.sleep(0.01)
                try:
                    frame = await asyncio.wait_for(gen.__anext__(), timeout=0.2)
                except (asyncio.TimeoutError, StopAsyncIteration):
                    continue
                body = json.loads(frame.removeprefix("data: ").strip())
                if body.get("event") == EVENT_QUOTE_UPDATE:
                    payload = body
                    break
        finally:
            await gen.aclose()

        assert payload is not None, "没收到 quote_update 帧"
        codes = {q["code"] for q in payload["quotes"]}
        assert codes == {"600519.SH"}, f"过滤失效: {codes}"

    def test_rest_fresh_flag_uses_fresh_path(self, client, monkeypatch):
        """?fresh=1 → 走 get_quotes_fresh(跳过缓存)"""
        seen: dict = {}

        class Svc:
            async def get_quotes(self, codes):
                seen["path"] = "cached"
                return [_mk_quote(c) for c in codes]

            async def get_quotes_fresh(self, codes):
                seen["path"] = "fresh"
                return [_mk_quote(c) for c in codes]

        monkeypatch.setattr("app.api.quotes.get_quote_service", lambda: Svc())

        r = client.get("/api/quotes?codes=600519.SH&fresh=true")
        assert r.status_code == 200
        assert seen["path"] == "fresh"

        r = client.get("/api/quotes?codes=600519.SH")
        assert r.status_code == 200
        assert seen["path"] == "cached"
