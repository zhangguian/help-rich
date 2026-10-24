"""计算器端点契约测试(/api/calculator + /api/calculator/review)

覆盖:
- /api/calculator 保持原样(before / after / 21 档 pnl_grid)
- /api/calculator/review 的响应结构与 verdict 枚举
- 卖出超过持仓 → 422 INSUFFICIENT_SHARES
- K 线不可用 → 502 DATA_SOURCE_UNAVAILABLE(不是 500)
- 市场环境 / 持仓读取失败 → 仍 200,降级写进 degraded
- 端点零 LLM(响应里没有任何 LLM 字段)
"""
from contextlib import ExitStack, contextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.modules.portfolio.service import Position
from app.services.decision_service import MarketContext
from app.services.kline_service import KLineSourceUnavailable

client = TestClient(app)

CODE = "002185.SZ"
VALID_VERDICTS = {"ok", "conditional", "not_recommended", "unknown"}


def _klines(n: int = 60) -> list[dict]:
    return [
        {
            "date": f"2026-01-{i + 1:02d}",
            "open": 10.0,
            "high": 10.5 + (i % 5) * 0.2,
            "low": 9.8,
            "close": 10.0 + (i % 7) * 0.3,
            "volume": 10000,
        }
        for i in range(n)
    ]


def _position(shares: int = 1000, total_cost: str = "17021.46") -> Position:
    return Position(
        stock_code=CODE,
        stock_name="华天科技",
        shares=shares,
        total_cost=Decimal(total_cost),
        realized_pnl=Decimal("-266.05"),
    )


@contextmanager
def _patched(
    position=None,
    env=None,
    env_error=None,
    position_error=None,
    kline_error=None,
    cash=None,
):
    """统一打补丁:K 线 / 行情 / 持仓 / 市场环境 / 账户资金 —— 全部不触网、不落库

    `cash=None` 表示账户资金读取返回 None(= 未填写);
    需要"未传该字段"的场景由 API 层自己判定(见 cash_available 入参测试)。
    """
    from app.modules.calculator import service as calc_service

    calc_service._slow_cache.clear()

    env_mock = (
        AsyncMock(return_value=env)
        if env_error is None
        else AsyncMock(side_effect=env_error)
    )
    pos_mock = (
        AsyncMock(return_value=position)
        if position_error is None
        else AsyncMock(side_effect=position_error)
    )
    kline_mock = (
        AsyncMock(return_value=_klines())
        if kline_error is None
        else AsyncMock(side_effect=kline_error)
    )
    cash_mock = AsyncMock(return_value=cash)
    with ExitStack() as stack:
        stack.enter_context(patch("app.modules.calculator.service.fetch_klines", kline_mock))
        stack.enter_context(
            patch("app.modules.calculator.service.QuoteService.get_quotes", AsyncMock(return_value=[]))
        )
        stack.enter_context(
            patch("app.modules.calculator.service.get_market_context", env_mock)
        )
        stack.enter_context(patch("app.modules.portfolio.service.get_position", pos_mock))
        stack.enter_context(patch("app.modules.portfolio.service.get_cash_available", cash_mock))
        yield
    calc_service._slow_cache.clear()


def _all_keys(obj) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        keys.update(obj.keys())
        for v in obj.values():
            keys.update(_all_keys(v))
    elif isinstance(obj, list):
        for v in obj:
            keys.update(_all_keys(v))
    return keys


def _body(action: str = "sell", shares: int = 100, price: str = "10.000") -> dict:
    return {
        "stock_code": CODE,
        "action": action,
        "tx_shares": shares,
        "tx_price": price,
    }


# ============================================================
# /api/calculator(保持原样)
# ============================================================

def test_calculator_endpoint_unchanged():
    with _patched(position=_position(), env=MarketContext()):
        r = client.post("/api/calculator", json=_body())
    assert r.status_code == 200
    body = r.json()
    assert {"input", "before", "after", "pnl_grid"}.issubset(body.keys())
    assert len(body["pnl_grid"]) == 21


# ============================================================
# /api/calculator/review
# ============================================================

def test_review_returns_expected_shape():
    with _patched(position=_position(), env=MarketContext()):
        r = client.post("/api/calculator/review", json=_body())
    assert r.status_code == 200
    body = r.json()
    for key in (
        "verdict",
        "headline",
        "reasons",
        "blockers",
        "price_check",
        "size_check",
        "t_assessment",
        "position_after",
        "risk_flags",
        "degraded",
    ):
        assert key in body, key
    assert body["verdict"] in VALID_VERDICTS
    assert isinstance(body["reasons"], list)
    assert isinstance(body["blockers"], list)
    assert isinstance(body["risk_flags"], list)
    assert isinstance(body["degraded"], list)


def test_review_has_no_llm_fields():
    with _patched(position=_position(), env=MarketContext()):
        r = client.post("/api/calculator/review", json=_body())
    keys = _all_keys(r.json())
    forbidden = {"ai", "ai_comment", "llm", "comment", "prompt", "raw_response"}
    assert not (keys & forbidden)


def test_review_sell_more_than_position_returns_422():
    with _patched(position=_position(shares=1000), env=MarketContext()):
        r = client.post("/api/calculator/review", json=_body(action="sell", shares=5000))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INSUFFICIENT_SHARES"


def test_review_kline_unavailable_returns_502_not_500():
    with _patched(
        position=_position(),
        env=MarketContext(),
        kline_error=KLineSourceUnavailable("日K数据源不可用"),
    ):
        r = client.post("/api/calculator/review", json=_body())
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"


def test_review_market_context_failure_still_returns_200():
    with _patched(position=_position(), env_error=RuntimeError("大盘情绪接口炸了")):
        r = client.post("/api/calculator/review", json=_body())
    assert r.status_code == 200
    assert "市场环境不可用" in r.json()["degraded"]


def test_review_position_failure_still_returns_200():
    with _patched(position_error=RuntimeError("database is locked"), env=MarketContext()):
        r = client.post("/api/calculator/review", json=_body())
    assert r.status_code == 200
    body = r.json()
    assert any("持仓读取失败" in d for d in body["degraded"])
    assert body["verdict"] in VALID_VERDICTS


def test_review_invalid_stock_code_returns_422():
    r = client.post("/api/calculator/review", json={**_body(), "stock_code": "abc"})
    assert r.status_code == 422


def test_review_t_assessment_shape():
    with _patched(position=_position(), env=MarketContext()):
        r = client.post("/api/calculator/review", json=_body())
    t = r.json()["t_assessment"]
    for key in (
        "suitable",
        "t_high",
        "t_low",
        "sell_trigger",
        "buyback_trigger",
        "your_price_in_range",
        "max_t_shares",
        "note",
    ):
        assert key in t, key
    assert isinstance(t["suitable"], bool)


def test_review_position_after_shape():
    with _patched(position=_position(), env=MarketContext()):
        r = client.post("/api/calculator/review", json=_body(action="sell", shares=100))
    pa = r.json()["position_after"]
    assert {"shares", "avg_cost", "total_cost", "realized_pnl"}.issubset(pa.keys())
    assert pa["shares"] == 900


def test_review_is_deterministic_for_same_input():
    with _patched(position=_position(), env=MarketContext()):
        a = client.post("/api/calculator/review", json=_body()).json()
        b = client.post("/api/calculator/review", json=_body()).json()
    assert a == b


# ============================================================
# 做 T 方向契约(t_directions)
# ============================================================

def test_review_returns_t_directions_shape():
    with _patched(position=_position(), env=MarketContext(), cash=Decimal("50000")):
        r = client.post("/api/calculator/review", json=_body())
    assert r.status_code == 200
    d = r.json()["t_directions"]
    for key in (
        "reverse",
        "forward",
        "recommended",
        "recommend_reason",
        "your_leg",
        # 刻意避开 "t_plus_1_note":前端 camelCase 转换只吃 "_小写字母",
        # "_1" 不会转成大写 → 前端拿到的是 tPlus_1Note,不是 tPlus1Note。
        # 字段名里带数字段会踩这个坑,所以后端直接用 "one"。
        "t_plus_one_note",
    ):
        assert key in d, key
    for side in ("reverse", "forward"):
        for key in (
            "key",
            "label",
            "applicable",
            "reason_code",
            "prerequisite",
            "max_shares",
            "max_amount",
            "steps",
            "status_text",
        ):
            assert key in d[side], f"{side}.{key}"
        assert isinstance(d[side]["applicable"], bool)
        assert isinstance(d[side]["steps"], list)


def test_review_t_directions_both_sides_always_present():
    """不适用的方向也要在响应里(前端据此灰显,不能靠缺字段判断)"""
    with _patched(position=_position(), env=MarketContext(), cash=None):
        r = client.post("/api/calculator/review", json=_body())
    d = r.json()["t_directions"]
    assert "reverse" in d and "forward" in d


def test_review_cash_available_field_accepted():
    """请求体带 cash_available → 用它算正T 股数"""
    with _patched(position=_position(), env=MarketContext(), cash=None):
        r = client.post(
            "/api/calculator/review",
            json={**_body(action="buy", price="10.000"), "cash_available": "3000.00"},
        )
    assert r.status_code == 200
    d = r.json()["t_directions"]
    assert d["forward"]["applicable"] is True
    assert d["forward"]["max_shares"] == 300


def test_review_cash_available_null_means_no_cash():
    """显式传 null → 明确"没有可用资金" → 正T 不可用且股数为 null"""
    with _patched(position=_position(), env=MarketContext(), cash=Decimal("99999")):
        r = client.post(
            "/api/calculator/review",
            json={**_body(action="buy", price="10.000"), "cash_available": None},
        )
    assert r.status_code == 200
    d = r.json()["t_directions"]
    assert d["forward"]["applicable"] is False
    assert d["forward"]["max_shares"] is None


def test_review_omitted_cash_falls_back_to_account_value():
    """不传该字段 → 用账户已保存的可用资金"""
    with _patched(position=_position(), env=MarketContext(), cash=Decimal("3000")):
        r = client.post(
            "/api/calculator/review",
            json=_body(action="buy", price="10.000"),
        )
    assert r.status_code == 200
    d = r.json()["t_directions"]
    assert d["forward"]["applicable"] is True
    assert d["forward"]["max_shares"] == 300


def test_review_negative_cash_rejected():
    with _patched(position=_position(), env=MarketContext()):
        r = client.post(
            "/api/calculator/review",
            json={**_body(), "cash_available": "-100"},
        )
    assert r.status_code == 422


def test_review_t_directions_has_no_llm_fields():
    with _patched(position=_position(), env=MarketContext(), cash=Decimal("50000")):
        r = client.post("/api/calculator/review", json=_body())
    keys = _all_keys(r.json()["t_directions"])
    forbidden = {"ai", "ai_comment", "llm", "comment", "prompt"}
    assert not (keys & forbidden)


def test_review_t_directions_keys_are_camelcase_safe():
    """字段名不得含「数字段」—— 前端 camelCase 转换只吃 "_小写字母"

    前端 `camelKey` 规则是 `key.replace(/_([a-z])/g, ...)`:
    `t_plus_1_note` → `tPlus_1Note`(下划线 + 数字 **不转**),
    而 TS 里若写成 `tPlus1Note` 就永远拿不到值 —— 类型全绿、运行期 undefined。
    这类 bug 只有锁住字段名才防得住。
    """
    import re

    with _patched(position=_position(), env=MarketContext(), cash=Decimal("50000")):
        r = client.post("/api/calculator/review", json=_body())
    keys = _all_keys(r.json()["t_directions"])
    bad = [k for k in keys if re.search(r"_\d", k)]
    assert bad == [], f"字段名含数字段,前端 camelCase 转换会失配: {bad}"
