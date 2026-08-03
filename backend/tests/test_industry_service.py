"""T-M2.1 行业归属三级兜底单测(纯函数 + async mock)"""
import asyncio
from pathlib import Path

from app.services.industry_service import (
    _load_industry_map,
    match_sina_industry_rank,
    resolve_industry,
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