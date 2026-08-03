"""T-M2.3 三线叠加服务单测(纯归一化 + mock 注入)"""
import asyncio

from app.services.overview_service import align_and_normalize, get_overview


def _run(coro):
    return asyncio.run(coro)


def _series(days: list[int], base: float) -> list[dict]:
    """[{date, close}] 构造:K 线行(日期用 2026-01-XX)"""
    out = []
    for d in days:
        out.append({
            "date": f"2026-01-{d:02d}",
            "open": base + d - 1,
            "high": base + d + 1,
            "low": base + d - 2,
            "close": base + d,
        })
    return out


class TestAlignNormalize:
    def test_basic_normalize(self):
        a = _series([1, 2, 3], 10)   # close 11,12,13
        b = _series([1, 2, 3], 20)   # 21,22,23
        c = _series([1, 2, 3], 30)   # 31,32,33
        out = align_and_normalize([a, b, c])
        assert len(out) == 3
        assert out[0][0]["close"] == 100.0
        # a: 11→100, 12→(12/11)*100
        assert out[0][1]["close"] == round(12 / 11 * 100, 2)
        assert out[1][1]["close"] == round(22 / 21 * 100, 2)
        assert out[2][1]["close"] == round(32 / 31 * 100, 2)

    def test_intersection_only(self):
        a = _series([1, 2, 3, 4], 10)
        b = _series([1, 3, 4, 5], 20)  # 缺 2026-01-02
        out = align_and_normalize([a, b])
        dates = [r["date"] for r in out[0]]
        assert dates == ["2026-01-01", "2026-01-03", "2026-01-04"]

    def test_empty_input(self):
        assert align_and_normalize([]) == []
        assert align_and_normalize([[], [], []]) == [[], [], []]

    def test_disjoint(self):
        a = _series([1, 2], 10)
        b = _series([3, 4], 20)
        assert align_and_normalize([a, b]) == [[], []]


class TestGetOverview:
    def test_success_via_mock(self, monkeypatch):
        async def fake_resolve(code):
            return {"industry": "白酒"}

        async def fake_stock(code, **kw):
            return _series([1, 2, 3], 10)

        async def fake_index(code, **kw):
            return _series([1, 2, 3], 20)

        async def fake_sector(name, **kw):
            return {"items": _series([1, 2, 3], 30)}

        monkeypatch.setattr("app.services.overview_service.resolve_industry", fake_resolve)
        monkeypatch.setattr("app.services.overview_service.fetch_klines", fake_stock)
        monkeypatch.setattr("app.services.overview_service._fetch_sina_kline", fake_index)
        monkeypatch.setattr("app.services.overview_service.get_sector_kline", fake_sector)

        data = _run(get_overview("600519.SH"))
        assert data["industry"] == "白酒"
        assert data["lines"]["stock"][0]["close"] == 100.0
        assert data["lines"]["index"][0]["close"] == 100.0
        assert data["lines"]["sector"][0]["close"] == 100.0
        assert data["sector_unavailable"] is False

    def test_sector_missing(self, monkeypatch):
        async def fake_resolve(code):
            return {"industry": None}

        async def fake_stock(code, **kw):
            return _series([1, 2, 3], 10)

        async def fake_index(code, **kw):
            return _series([1, 2, 3], 20)

        monkeypatch.setattr("app.services.overview_service.resolve_industry", fake_resolve)
        monkeypatch.setattr("app.services.overview_service.fetch_klines", fake_stock)
        monkeypatch.setattr("app.services.overview_service._fetch_sina_kline", fake_index)

        data = _run(get_overview("830799.BJ"))
        assert data["lines"]["sector"] == []
        assert data["sector_unavailable"] is False
        assert data["lines"]["stock"][0]["close"] == 100.0