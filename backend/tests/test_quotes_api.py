"""/api/quotes 端点测试(批量行情 + 股票代码规范化)

- 端点允许纯 6 位代码(自动补市场后缀)
- 端点拒绝非法代码
- 端点允许超过 50(放宽到 200)
"""
from decimal import Decimal
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.data.unified import UnifiedQuote
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


class FakeQuoteService:
    """假行情服务:对每个规范化 code 返回固定价格"""

    def __init__(self, name: str = "测试股", price: str = "10.00", prev: str = "9.50"):
        self.name = name
        self.price = price
        self.prev = prev
        self.last_codes: list[str] = []

    async def get_quotes(self, codes):
        self.last_codes = list(codes)
        out = []
        for code in codes:
            p, pc = Decimal(self.price), Decimal(self.prev)
            out.append(
                UnifiedQuote(
                    code=code,
                    name=self.name,
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
            )
        return out

    async def get_quote(self, code):
        out = await self.get_quotes([code])
        return out[0] if out else None


@pytest.fixture()
def patch_quotes(monkeypatch):
    svc = FakeQuoteService()
    monkeypatch.setattr("app.api.quotes.get_quote_service", lambda: svc)
    return svc


def test_batch_normalizes_bare_codes(client, patch_quotes):
    """纯 6 位代码自动补市场后缀(159599→159599.SZ 等)"""
    r = client.get("/api/quotes?codes=159599,000001,600519")
    assert r.status_code == 200, r.text
    sent = set(patch_quotes.last_codes)
    # 1xxxxx 走 SZ,0xxxxx 走 SZ,6xxxxx 走 SH
    assert "159599.SZ" in sent
    assert "000001.SZ" in sent
    assert "600519.SH" in sent
    # 端点返回的 code 是规范后的
    out_codes = {q["code"] for q in r.json()}
    assert out_codes == {"159599.SZ", "000001.SZ", "600519.SH"}


def test_batch_invalid_code_rejected(client, patch_quotes):
    """非法代码触发 422"""
    r = client.get("/api/quotes?codes=12x,600519.SH")
    assert r.status_code == 422
    assert "12x" in r.json()["detail"]


def test_batch_all_dotted_codes_passthrough(client, patch_quotes):
    """已经带后缀的代码原样传给后端 service"""
    r = client.get("/api/quotes?codes=600519.SH,000001.SZ")
    assert r.status_code == 200
    assert set(patch_quotes.last_codes) == {"600519.SH", "000001.SZ"}


def test_batch_lowercase_market_normalized(client, patch_quotes):
    """小写 .sh/.sz 也被规范化(走 normalize_code)"""
    r = client.get("/api/quotes?codes=600519.sh")
    assert r.status_code == 200
    assert "600519.SH" in {q["code"] for q in r.json()}


def test_single_endpoint_normalizes(client, patch_quotes):
    """/api/quotes/{code} 单只端点也走 normalize_code"""
    r = client.get("/api/quotes/000001")
    assert r.status_code == 200
    assert patch_quotes.last_codes == ["000001.SZ"]
    assert r.json()["code"] == "000001.SZ"


def test_single_invalid_rejected(client, patch_quotes):
    r = client.get("/api/quotes/12x")
    assert r.status_code == 422


def test_empty_codes_rejected(client, patch_quotes):
    """空字符串视为空 → 422"""
    r = client.get("/api/quotes?codes=")
    assert r.status_code == 422


def test_oversize_rejected(client, patch_quotes):
    """超过 200 个返回 422"""
    codes = ",".join(f"6{i:05d}" for i in range(201))
    r = client.get(f"/api/quotes?codes={codes}")
    assert r.status_code == 422