"""T-M2.1 行业归属三级兜底单测(纯函数 + async mock)"""
import asyncio
from pathlib import Path

from app.services.industry_service import (
    _load_industry_map,
    match_sina_industry_rank,
    resolve_industry,
    resolve_industry_sync,
)

_MAP = Path(__file__).resolve().parents[1] / "app" / "data" / "industry_map.json"


def _run(coro):
    return asyncio.run(coro)


class TestOfflineMap:
    def test_map_loads(self):
        m = _load_industry_map()
        assert isinstance(m, dict)
        assert m.get("600519.SH"), "茅台应命中行业"

    def test_map_readable_utf8(self):
        d = _load_industry_map()
        name = d.get("600519.SH", "")
        assert "�" not in name
        assert len(name) > 1


class TestMatchSinaRank:
    def test_hit(self):
        items = [
            {"name": "银行", "top_stock": {"code": "600036.SH"}},
            {"name": "白酒", "top_stock": {"code": "600519.SH"}},
        ]
        assert match_sina_industry_rank(items, "600519.SH") == {"name": "白酒"}

    def test_miss(self):
        assert match_sina_industry_rank([], "600519.SH") is None


class TestResolveThreeTier:
    def test_first_local_hit(self, monkeypatch):
        async def fake_sina(code):
            raise AssertionError("一级命中不应走新浪")

        monkeypatch.setattr("app.services.industry_service._resolve_sina", fake_sina)
        r = _run(resolve_industry("600519.SH"))
        assert r["source"] == "baostock"
        assert r["industry"]

    def test_second_sina_fallback(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.industry_service._resolve_local", lambda code: None
        )
        async def fake_sina(code):
            return "银行"

        monkeypatch.setattr(
            "app.services.industry_service._resolve_sina",
            fake_sina,
        )
        r = _run(resolve_industry("600036.SH"))
        assert r["source"] == "sina"
        assert r["industry"] == "银行"

    def test_third_degrade(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.industry_service._resolve_local", lambda code: None
        )
        async def fake_sina(code):
            return None

        monkeypatch.setattr(
            "app.services.industry_service._resolve_sina",
            fake_sina,
        )
        r = _run(resolve_industry("888888.SH"))
        assert r["industry"] is None
        assert r["source"] is None
        assert r["note"]


class TestEtfIndexFallback:
    """ETF 兜底:baostock → 新浪 → **ETF 跟踪指数** → 降级

    ETF 不在个股行业表里 → 用「跟踪指数」作为行业语义的替代表达。
    """

    @staticmethod
    def _no_stock_sources(monkeypatch):
        monkeypatch.setattr(
            "app.services.industry_service._resolve_local", lambda code: None
        )

        async def fake_sina(code):
            return None

        monkeypatch.setattr(
            "app.services.industry_service._resolve_sina",
            fake_sina,
        )

    def test_domestic_etf_returns_tracking_index(self, monkeypatch):
        self._no_stock_sources(monkeypatch)
        r = _run(resolve_industry("510300.SH"))
        assert r["source"] == "etf_index"
        assert r["industry"] == "跟踪沪深 300"
        assert "宽基" in r["note"]

    def test_sz_etf_returns_tracking_index(self, monkeypatch):
        self._no_stock_sources(monkeypatch)
        r = _run(resolve_industry("159915.SZ"))
        assert r["source"] == "etf_index"
        assert r["industry"] == "跟踪创业板指"

    def test_industry_etf_category_label(self, monkeypatch):
        self._no_stock_sources(monkeypatch)
        r = _run(resolve_industry("512480.SH"))
        assert r["source"] == "etf_index"
        assert "行业" in r["note"]

    def test_qdii_etf_category_label(self, monkeypatch):
        self._no_stock_sources(monkeypatch)
        r = _run(resolve_industry("513050.SH"))
        assert r["source"] == "etf_index"
        assert "QDII" in r["note"]

    def test_commodity_etf_category_label(self, monkeypatch):
        self._no_stock_sources(monkeypatch)
        r = _run(resolve_industry("518880.SH"))
        assert r["source"] == "etf_index"
        assert "商品" in r["note"]

    def test_etf_outside_table_falls_to_degrade(self, monkeypatch):
        """表外 ETF(有格式但无表项)→ 降级,不编跟踪指数"""
        self._no_stock_sources(monkeypatch)
        r = _run(resolve_industry("510999.SH"))
        assert r["industry"] is None
        assert r["source"] is None
        assert r["note"]

    def test_etf_does_not_call_sina(self, monkeypatch):
        """ETF 必须先命中品种表 —— 不能为「注定不命中」付一次网络往返

        新浪行业反查要打网络(且会超时)。ETF 不在个股行业表里,
        若顺序是 baostock → 新浪 → ETF,每个 ETF 的每次请求都白等一次。
        """
        async def boom(code):
            raise AssertionError("ETF 不应走新浪(品种表命中即可)")

        monkeypatch.setattr("app.services.industry_service._resolve_sina", boom)
        r = _run(resolve_industry("510300.SH"))
        assert r["source"] == "etf_index"
        assert r["industry"] == "跟踪沪深 300"

    def test_stock_still_falls_back_to_sina(self, monkeypatch):
        """股票路径不受影响:baostock 未命中仍走新浪"""
        monkeypatch.setattr(
            "app.services.industry_service._resolve_local", lambda code: None
        )

        async def fake_sina(code):
            return "银行"

        monkeypatch.setattr(
            "app.services.industry_service._resolve_sina",
            fake_sina,
        )
        r = _run(resolve_industry("600036.SH"))
        assert r["source"] == "sina"
        assert r["industry"] == "银行"

    def test_stock_not_affected(self, monkeypatch):
        """股票走 baostock,不被 ETF 路径影响"""
        async def fake_sina(code):
            raise AssertionError("一级命中不应走新浪")

        monkeypatch.setattr("app.services.industry_service._resolve_sina", fake_sina)
        r = _run(resolve_industry("600519.SH"))
        assert r["source"] == "baostock"
        assert r["industry"]


class TestResolveIndustrySync:
    """纯本地版:只查离线表 + 品种表,绝不打网络

    用途:analysis 端点要往响应里挂一个行业 chip,
    不值得为它付一次网络往返(新浪行业反查会超时)。
    """

    def test_stock_uses_baostock(self):
        r = resolve_industry_sync("600519.SH")
        assert r["source"] == "baostock"
        assert r["industry"]

    def test_etf_uses_tracking_index(self):
        r = resolve_industry_sync("513100.SH")
        assert r["source"] == "etf_index"
        assert r["industry"] == "跟踪纳斯达克 100"
        assert "QDII" in r["note"]

    def test_unknown_etf_returns_none(self):
        """表外 ETF → 不编跟踪指数"""
        r = resolve_industry_sync("159934.SZ")
        assert r["industry"] is None
        assert r["source"] is None

    def test_never_calls_sina(self, monkeypatch):
        async def boom(code):
            raise AssertionError("同步版不得打网络")

        monkeypatch.setattr("app.services.industry_service._resolve_sina", boom)
        assert resolve_industry_sync("510300.SH")["source"] == "etf_index"
        assert resolve_industry_sync("600519.SH")["source"] == "baostock"