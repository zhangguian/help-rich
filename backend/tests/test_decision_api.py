"""决策端点契约测试

覆盖:
- 非法代码 → 422 INVALID_STOCK_CODE
- 正常响应结构(设计文档 §5.2)
- K 线不可用 → 502 DATA_SOURCE_UNAVAILABLE(不是 500)
- 市场环境不可用 → 仍 200(降级,不失败)
- 端点零 LLM(不触发任何 LLM 服务)
- 空仓时 cost_basis 为 None(Position.avg_cost 空仓时是 Decimal("0"))
"""
from contextlib import ExitStack, contextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api import stock as stock_api
from app.main import app
from app.modules.portfolio.service import Position
from app.services.decision_service import MarketContext
from app.services.kline_service import KLineSourceUnavailable

client = TestClient(app)

CODE = "002185.SZ"


def _klines(n: int = 60) -> list[dict]:
    return [
        {
            "date": f"2026-01-{i + 1:02d}", "open": 10.0, "high": 10.5,
            "low": 9.8, "close": 10.2, "volume": 10000,
        }
        for i in range(n)
    ]


@contextmanager
def _patched(position=None, env=None, env_error=None):
    """统一打补丁:行情 / 持仓 / 市场环境 —— 全部不触网、不落库"""
    env_mock = AsyncMock(return_value=env) if env_error is None else AsyncMock(side_effect=env_error)
    with ExitStack() as stack:
        stack.enter_context(
            patch("app.api.stock.fetch_klines", AsyncMock(return_value=_klines()))
        )
        stack.enter_context(
            patch("app.api.stock.QuoteService.get_quotes", AsyncMock(return_value=[]))
        )
        stack.enter_context(
            patch("app.api.stock.get_position", AsyncMock(return_value=position))
        )
        stack.enter_context(
            patch("app.api.stock.get_market_context", env_mock)
        )
        yield


def _all_keys(obj) -> set[str]:
    """递归收集响应里所有 dict 的 key(用于断言无 LLM 字段)"""
    keys: set[str] = set()
    if isinstance(obj, dict):
        keys.update(obj.keys())
        for v in obj.values():
            keys.update(_all_keys(v))
    elif isinstance(obj, list):
        for v in obj:
            keys.update(_all_keys(v))
    return keys


def test_invalid_code_returns_422():
    r = client.get("/api/stock/123/decision")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INVALID_STOCK_CODE"


@pytest.mark.asyncio
async def test_decision_endpoint_returns_shape():
    with _patched(env=MarketContext()):
        r = client.get(f"/api/stock/{CODE}/decision")
    assert r.status_code == 200
    body = r.json()
    assert "decision" in body
    d = body["decision"]
    for key in ("verdict", "headline", "actions", "role", "trend_state",
                "t_plan", "do_not", "data_quality"):
        assert key in d


def test_kline_unavailable_returns_502_not_500():
    """K 线完全不可用 → 502 DATA_SOURCE_UNAVAILABLE(不是 500)"""
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "app.api.stock.fetch_klines",
                AsyncMock(side_effect=KLineSourceUnavailable("日K数据源不可用")),
            )
        )
        stack.enter_context(
            patch("app.api.stock.QuoteService.get_quotes", AsyncMock(return_value=[]))
        )
        stack.enter_context(
            patch("app.api.stock.get_position", AsyncMock(return_value=None))
        )
        r = client.get(f"/api/stock/{CODE}/decision")
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"


def test_market_context_failure_still_returns_200():
    """市场环境聚合抛异常 → 仍 200,降级写进 data_quality.degraded"""
    with _patched(env_error=RuntimeError("大盘情绪接口炸了")):
        r = client.get(f"/api/stock/{CODE}/decision")
    assert r.status_code == 200
    d = r.json()["decision"]
    assert "市场环境不可用" in d["data_quality"]["degraded"]
    assert "市场环境不可用" in d["market_env"]["degraded"]


def test_market_context_none_still_returns_200():
    """get_market_context 返回 None → 端点兜底成 MarketContext,仍 200"""
    with _patched(env=None):
        r = client.get(f"/api/stock/{CODE}/decision")
    assert r.status_code == 200
    d = r.json()["decision"]
    assert "市场环境不可用" in d["data_quality"]["degraded"]
    # 决策照常产出,不是空壳
    assert d["verdict"] in ("buy", "add", "hold", "reduce", "sell", "wait")
    assert d["headline"]


def test_endpoint_never_calls_llm():
    """零 LLM:任何 LLM 服务函数都不得被调用,响应里也不得有 LLM 字段"""
    with ExitStack() as stack:
        stack.enter_context(
            patch("app.api.stock.get_stock_analysis", MagicMock())
        )
        stack.enter_context(
            patch("app.api.stock.stream_stock_analysis", MagicMock())
        )
        stack.enter_context(
            patch("app.api.stock.ask_stock_question", MagicMock())
        )
        stack.enter_context(
            patch("app.api.stock.check_llm_available", MagicMock())
        )
        stack.enter_context(
            patch("app.api.stock.get_market_context", AsyncMock(return_value=MarketContext()))
        )
        stack.enter_context(
            patch("app.api.stock.fetch_klines", AsyncMock(return_value=_klines()))
        )
        stack.enter_context(
            patch("app.api.stock.QuoteService.get_quotes", AsyncMock(return_value=[]))
        )
        stack.enter_context(
            patch("app.api.stock.get_position", AsyncMock(return_value=None))
        )
        r = client.get(f"/api/stock/{CODE}/decision")

    assert r.status_code == 200
    keys = _all_keys(r.json())
    assert not keys & {"ai", "ai_source", "llm", "advice", "chat", "stream", "tokens"}


def test_llm_functions_not_invoked():
    """显式断言:LLM 相关入口未被调用(用独立 spy 计数)"""
    spies = {
        name: MagicMock() for name in
        ("get_stock_analysis", "stream_stock_analysis",
         "ask_stock_question", "check_llm_available")
    }
    with ExitStack() as stack:
        for name, spy in spies.items():
            stack.enter_context(patch(f"app.api.stock.{name}", spy))
        stack.enter_context(
            patch("app.api.stock.get_market_context", AsyncMock(return_value=MarketContext()))
        )
        stack.enter_context(
            patch("app.api.stock.fetch_klines", AsyncMock(return_value=_klines()))
        )
        stack.enter_context(
            patch("app.api.stock.QuoteService.get_quotes", AsyncMock(return_value=[]))
        )
        stack.enter_context(
            patch("app.api.stock.get_position", AsyncMock(return_value=None))
        )
        r = client.get(f"/api/stock/{CODE}/decision")

    assert r.status_code == 200
    for name, spy in spies.items():
        spy.assert_not_called()


def test_empty_position_cost_basis_is_none():
    """修正 4:空仓时 Position.avg_cost 是 Decimal('0'),cost_basis 必须给 None"""
    spy = MagicMock(wraps=stock_api.build_decision)
    with ExitStack() as stack:
        stack.enter_context(patch("app.api.stock.build_decision", spy))
        stack.enter_context(
            patch("app.api.stock.get_market_context", AsyncMock(return_value=MarketContext()))
        )
        stack.enter_context(
            patch("app.api.stock.fetch_klines", AsyncMock(return_value=_klines()))
        )
        stack.enter_context(
            patch("app.api.stock.QuoteService.get_quotes", AsyncMock(return_value=[]))
        )
        stack.enter_context(
            patch(
                "app.api.stock.get_position",
                AsyncMock(return_value=Position(stock_code=CODE, shares=0)),
            )
        )
        r = client.get(f"/api/stock/{CODE}/decision")

    assert r.status_code == 200
    ctx = spy.call_args.args[0]
    assert ctx.shares == 0
    assert ctx.cost_basis is None
    assert ctx.position_status == "empty"


def test_holding_position_cost_basis_and_shares():
    """有持仓 → cost_basis / shares 正确落到 DecisionContext"""
    pos = Position(
        stock_code=CODE,
        stock_name="华天科技",
        shares=1000,
        total_cost=Decimal("9500"),
    )
    spy = MagicMock(wraps=stock_api.build_decision)
    with ExitStack() as stack:
        stack.enter_context(patch("app.api.stock.build_decision", spy))
        stack.enter_context(
            patch("app.api.stock.get_market_context", AsyncMock(return_value=MarketContext()))
        )
        stack.enter_context(
            patch("app.api.stock.fetch_klines", AsyncMock(return_value=_klines()))
        )
        stack.enter_context(
            patch("app.api.stock.QuoteService.get_quotes", AsyncMock(return_value=[]))
        )
        stack.enter_context(
            patch("app.api.stock.get_position", AsyncMock(return_value=pos))
        )
        r = client.get(f"/api/stock/{CODE}/decision")

    assert r.status_code == 200
    ctx = spy.call_args.args[0]
    assert ctx.shares == 1000
    assert ctx.cost_basis == pytest.approx(9.5)
    assert ctx.stock_name == "华天科技"


def test_existing_analysis_endpoint_still_works():
    """既有端点行为未被改动:/analysis 仍走原来的 get_stock_analysis"""
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "app.api.stock.get_stock_analysis",
                AsyncMock(return_value={"indicators": {}, "ai": None, "ai_source": "none"}),
            )
        )
        stack.enter_context(
            patch("app.api.stock.fetch_klines", AsyncMock(return_value=_klines()))
        )
        stack.enter_context(
            patch("app.api.stock.QuoteService.get_quotes", AsyncMock(return_value=[]))
        )
        stack.enter_context(
            patch("app.api.stock.get_position", AsyncMock(return_value=None))
        )
        r = client.get(f"/api/stock/{CODE}/analysis")

    assert r.status_code == 200
    assert r.json()["position_status"] == "empty"
    assert r.json()["from_cache"] is False


def test_existing_industry_endpoint_still_works():
    """既有端点行为未被改动:/industry 仍走原来的 resolve_industry"""
    with patch(
        "app.api.stock.resolve_industry",
        AsyncMock(return_value={"industry": "C39", "source": "offline"}),
    ):
        r = client.get(f"/api/stock/{CODE}/industry")
    assert r.status_code == 200
    assert r.json()["industry"] == "C39"
