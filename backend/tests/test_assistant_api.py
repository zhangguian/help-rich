"""全局 AI 助手测试(阶段 T4 · 后端)

覆盖:
  1. LLM 未配置 → **流开始前** 503(不是流里 error)
  2. 事实包组装:选中票 / 持仓 / ★关注 / 指数 / 作战计划 / 盘中复盘
  3. 降级纪律:某段取数失败 → 只标进 `unavailable`,其余照常
  4. prompt 纪律:数字只来自事实包;事实包里没有就说没有
  5. 历史截断到最近 6 轮
  6. SSE 事件格式:text 增量 / done / error

**不打桩真实网络**:行情、作战计划、复盘、LLM 全部在边界处替换。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import assistant_service as svc

client = TestClient(app)


# ============================ 假数据 ============================


class _FakeQuoteService:
    async def get_quotes(self, codes):
        out = []
        for c in codes:
            if c == "600519.SH":
                out.append(SimpleNamespace(
                    code=c, name="贵州茅台",
                    current_price=12.30, change_pct=-1.2,
                ))
            elif c == "000001.SH":
                out.append(SimpleNamespace(
                    code=c, name="上证指数",
                    current_price=3713.03, change_pct=-1.48,
                ))
        return out


def _fake_position(code="600519.SH", name="贵州茅台", shares=100, cost=10.0):
    return SimpleNamespace(
        stock_code=code,
        stock_name=name,
        shares=shares,
        total_cost=cost * shares,
        avg_cost=cost,
        realized_pnl=0.0,
    )


class _FakeWatch:
    def __init__(self, items):
        self._items = items

    async def list_all(self):
        return self._items


FAKE_PLAN = {
    "plan_date": "2026-10-22",
    "target_date": "2026-10-23",
    "outlook": {
        "stance": "bearish",
        "stance_label": "偏空",
        "summary": "盘前四维度规则推断:倾向偏空(4/4 维有效),支撑 3703.12,压力 3743.09/3824.82",
        "dims": [{"key": "volume", "label": "量能", "score": -1, "state": "bear", "detail": "缩量"}],
        "key_levels": {"support": [3703.12], "resistance": [3743.09, 3824.82]},
    },
    "meta": {"scope_count": 11},
    "items": [
        {
            "stock_code": "600519.SH", "stock_name": "贵州茅台",
            "item_kind": "stop", "direction": "sell", "label": "明日止损",
            "trigger_price": 12.39,
            "basis": ["跌破 12.39 元无条件减仓"],
            "invalid_if": "收盘站回 12.39 元上方则不看止损",
        }
    ],
}

# 盘中复盘:真实行结构是 {"trade_date", "slot", "payload": {...}}
# (早期版本这里用的是扁平 dict,结果测试全绿、实机却是空的 —— 形状必须对齐真实契约)
FAKE_REVIEW_ROW = {
    "trade_date": "2026-10-22",
    "slot": "11:30",
    "payload": {
        "trade_date": "2026-10-22",
        "slot": "11:30",
        "market_opinion": {
            "stance": "bearish",
            "stance_label": "偏空",
            "summary": "盘前四维度规则推断:倾向偏空(4/4 维有效),支撑 3703.12",
            "basis": "盘前四维度规则推断（非盘中重算）",
            "key_levels": {"support": [3703.12], "resistance": [3743.09]},
            "dims": [],
            "degraded": False,
        },
        "actions": [
            {
                "stock_code": "600519.SH", "stock_name": "贵州茅台",
                "label": "明日止损", "direction": "sell",
                "trigger_price": 12.39, "current_price": 12.30,
                "gap_pct": -0.73, "action_state": "已到价待执行",
                "basis": ["跌破 12.39 元无条件减仓"],
            }
        ],
        "extra_lines": ["🚀 600519.SH 贵州茅台 -1.2%"],
        "degraded": False,
    },
}


@pytest.fixture
def wired(monkeypatch):
    """把助手的全部外部依赖替换掉(行情 / 持仓 / 自选 / 计划 / 复盘)"""

    async def _positions():
        return [_fake_position()]

    async def _plan(_d):
        return FAKE_PLAN

    async def _reviews(_d):
        return [FAKE_REVIEW_ROW]

    monkeypatch.setattr(svc, "get_all_positions", _positions)
    monkeypatch.setattr(svc, "QuoteService", _FakeQuoteService)
    monkeypatch.setattr(svc, "get_plan", _plan)
    monkeypatch.setattr(svc, "get_reviews", _reviews)
    monkeypatch.setattr(
        svc, "watchlist_repo",
        _FakeWatch([
            SimpleNamespace(stock_code="600519.SH", stock_name="贵州茅台", is_favorite=True),
            SimpleNamespace(stock_code="000001.SZ", stock_name="平安银行", is_favorite=False),
        ]),
    )
    return monkeypatch


# ============================ 事实包 ============================


@pytest.mark.anyio
async def test_context_contains_all_sections(wired):
    ctx = await svc.build_context("600519.SH")
    assert ctx["selected"]["code"] == "600519.SH"
    assert ctx["selected"]["price"] == 12.30
    assert len(ctx["positions"]) == 1
    assert ctx["positions"][0]["floating_pnl_pct"] == 23.0  # (12.30-10)/10
    # ★关注只收 is_favorite=True
    assert [f["code"] for f in ctx["favorites"]] == ["600519.SH"]
    assert any(i["code"] == "000001.SH" for i in ctx["indexes"])
    assert ctx["plan"]["stance_label"] == "偏空"
    assert ctx["intraday_reviews"][0]["slot"] == "11:30"
    assert ctx["intraday_reviews"][0]["actions"][0]["action_state"] == "已到价待执行"
    assert ctx["unavailable"] == []


@pytest.mark.anyio
async def test_context_marks_unavailable_but_keeps_rest(monkeypatch, wired):
    """某段挂了就标 unavailable,其余照常 —— 不整体崩掉"""

    async def _boom(_d):
        raise RuntimeError("盘坏了")

    monkeypatch.setattr(svc, "get_plan", _boom)
    ctx = await svc.build_context("600519.SH")
    assert "今日作战计划" in ctx["unavailable"]
    assert ctx["plan"] is None
    # 其余段落仍然可用
    assert ctx["selected"]["price"] == 12.30
    assert len(ctx["positions"]) == 1


@pytest.mark.anyio
async def test_context_marks_position_failure_as_unavailable(monkeypatch, wired):
    """持仓取数失败也要进 unavailable —— 助手得知道「持仓数据取不到」,
    而不是当成「你没持仓」"""

    async def _boom():
        raise RuntimeError("表炸了")

    monkeypatch.setattr(svc, "get_all_positions", _boom)
    ctx = await svc.build_context("600519.SH")
    assert "持仓" in ctx["unavailable"]
    assert ctx["positions"] == []
    # 其余照常
    assert ctx["selected"]["price"] == 12.30


@pytest.mark.anyio
async def test_context_without_selected_stock(wired):
    """前端还没选中票 → selected 为 None,其余照常"""
    ctx = await svc.build_context(None)
    assert ctx["selected"] is None
    assert ctx["positions"]


# ============================ Prompt 纪律 ============================


def test_system_prompt_forbids_fabrication():
    p = svc.SYSTEM_PROMPT
    assert "禁止编造" in p
    assert "事实包" in p
    assert "禁止推算" in p


def test_system_prompt_requires_verbatim_prices():
    """实测抓到:止损价 11.625 被 LLM 四舍五入成 11.62 → prompt 必须钉死「逐字引用」。

    规则:LLM 只翻译不计算,价格连小数位都不许动(改一个数字就是改判)。
    """
    p = svc.SYSTEM_PROMPT
    assert "逐字引用" in p
    assert "不要四舍五入" in p
    # user prompt 也要复述一遍(LLM 更看最近的指令)
    msg = svc.build_user_prompt("现价多少?", {"selected": None, "positions": []})
    assert "逐字原样引用" in msg
    assert "不要四舍五入" in msg


def test_user_prompt_contains_facts_and_question():
    ctx = {"selected": {"code": "600519.SH"}, "positions": []}
    msg = svc.build_user_prompt("今天该盯哪只?", ctx)
    assert "600519.SH" in msg
    assert "今天该盯哪只?" in msg
    # 事实包是 JSON,能直接解析出来
    start = msg.index("【事实包】") + len("【事实包】")
    end = msg.index("【用户问题】")
    parsed = json.loads(msg[start:end].strip())
    assert parsed["selected"]["code"] == "600519.SH"


def test_history_truncated_to_6_turns():
    hist = []
    for i in range(20):
        hist.append({"role": "user", "text": f"问{i}"})
        hist.append({"role": "ai", "text": f"答{i}"})
    msgs = svc._to_llm_messages(hist)
    assert len(msgs) == svc.MAX_HISTORY_TURNS * 2
    # 保留完整配对:从「问14/答14」这一对开始,到最后「问19/答19」
    assert msgs[0] == {"role": "user", "content": "问14"}
    assert msgs[-1] == {"role": "assistant", "content": "答19"}
    # user/assistant 必须成对出现,不能只剩一半
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant"] * (svc.MAX_HISTORY_TURNS)


def test_history_maps_ai_to_assistant():
    msgs = svc._to_llm_messages([{"role": "ai", "text": "答"}])
    assert msgs == [{"role": "assistant", "content": "答"}]


# ============================ API ============================


def test_api_returns_503_before_stream_when_llm_missing(monkeypatch, wired):
    """LLM 未配置 → 流开始前 503(响应体是 detail,不是 SSE)"""

    async def _no_llm():
        return None

    monkeypatch.setattr(svc, "_get_llm", _no_llm)
    r = client.post("/api/assistant/chat/stream", json={"question": "你好"})
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["detail"]["code"] == "LLM_UNAVAILABLE"


def test_api_rejects_empty_question():
    r = client.post("/api/assistant/chat/stream", json={"question": "   "})
    assert r.status_code == 422


def test_api_streams_text_then_done(monkeypatch, wired):
    """SSE 事件格式:text 增量 → done"""
    from app.api import assistant as api

    async def _fake_stream(question, stock_code=None, history=None):
        assert stock_code == "600519.SH"
        yield "你"
        yield "好"

    monkeypatch.setattr(api, "check_assistant_available", _ok)
    monkeypatch.setattr(api, "stream_assistant_answer", _fake_stream)

    with client.stream(
        "POST", "/api/assistant/chat/stream",
        json={"question": "你好", "stock_code": "600519"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(chunk for chunk in resp.iter_text())

    events = [
        json.loads(line[len("data: "):])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    assert events[0] == {"text": "你"}
    assert events[1] == {"text": "好"}
    assert events[-1] == {"done": True}


def test_api_streams_error_event(monkeypatch, wired):
    """流中途失败 → data:{"error":...}"""
    from app.api import assistant as api
    from app.services.assistant_service import AssistantUnavailable

    async def _boom(question, stock_code=None, history=None):
        raise AssistantUnavailable("LLM 调用失败: 炸了")
        yield ""  # pragma: no cover

    monkeypatch.setattr(api, "check_assistant_available", _ok)
    monkeypatch.setattr(api, "stream_assistant_answer", _boom)

    with client.stream(
        "POST", "/api/assistant/chat/stream", json={"question": "你好"}
    ) as resp:
        body = "".join(chunk for chunk in resp.iter_text())

    events = [
        json.loads(line[len("data: "):])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    assert "error" in events[0]
    assert "炸了" in events[0]["error"]
    assert not any(e.get("done") for e in events)


async def _ok():
    return None
