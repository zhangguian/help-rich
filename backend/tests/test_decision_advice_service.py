"""操作建议服务单测(decision_advice_service)

三条铁律在这里被锁死:
1. 事实包只含确定性数字(不含任何 LLM 措辞);
2. 规则白话在缺字段时仍能生成(永不空白);
3. LLM 失败 → source='rule'(退回规则文案),绝不让卡片空掉。
"""
import json

import pytest

from app.services import decision_advice_service as svc
from app.services.decision_advice_service import (
    build_advice,
    build_fact_pack,
    clear_advice_cache,
    compose_rule_advice,
)


def _decision(**over) -> dict:
    base = {
        "stock_code": "002185.SZ",
        "stock_name": "华天科技",
        "verdict": "hold",
        "headline": "现价 16.19 元,等触发:涨到 19.16 元可解套(需涨 5.1%)",
        "role": "解套参考",
        "confidence": "medium",
        "position_status": "loss",
        "actions": [
            {
                "kind": "watch", "label": "解套路径",
                "condition": "涨到 19.16 元可解套(需涨 5.1%)",
                "price": 19.16, "basis": ["持仓成本 17.02 元"], "status": "armed",
            },
            {
                "kind": "add", "label": "补仓摊薄",
                "condition": "暂不补仓", "price": 16.19,
                "basis": ["下跌通道"], "status": "blocked",
            },
        ],
        "suggestions": {
            "price": {"label": "价位", "value": "涨到 19.16 元可解套(需涨 5.1%)"},
            "stop_loss": {"label": "止损", "value": "13.20 元(距现价 -18.5%)"},
            "position": {"label": "仓位", "value": "解套优先,减仓不追补"},
            "trigger": {"label": "触发", "value": "涨到 19.16 元(P80 分位)"},
            "timing": {"label": "时间", "value": "已持有 23 天,回本还需 +5.1%"},
            "avoid": {"label": "不动", "value": "下跌通道中不要抄底"},
        },
        "t_plan": {"suitable": True, "t_high": 16.86, "t_low": 15.29, "amplitude_pct": 9.7},
        "grid_plan": {
            "suitable": False, "mode": None,
            "unsuitable_signals": "下跌通道中不要布网格:越买越套",
        },
        "cost_anchor": {"pnl_pct": -4.9, "break_even_gap_pct": 5.1},
        "time_window": {"holding_days": 23, "overdue": True},
        "cost_effect": {"roundtrip_fee_pct": 0.102, "fee_basis": "default_estimate"},
        "instrument_rule": {"kind": "stock", "t0": False, "notes": ["T+1"]},
        "concentration": {"cost_share_pct": 12.0, "level": "low"},
        "stop_loss": {"price": 13.2, "basis": "跌破即止损"},
        "position_pct": "解套优先,减仓不追补",
        "do_not": ["下跌通道中不要抄底"],
        "data_quality": {"degraded": ["费用设置未启用,费用按默认档估算"]},
    }
    base.update(over)
    return base


# ---------------------------------------------------------------- 事实包

def test_fact_pack_only_keeps_executable_actions():
    pack = build_fact_pack(_decision())
    assert len(pack["actions"]) == 1
    assert pack["actions"][0]["status"] == "armed"


def test_fact_pack_carries_grid_and_suggestions():
    pack = build_fact_pack(_decision(), as_of="2026-10-24")
    assert pack["grid_plan"]["unsuitable_signals"]
    assert pack["suggestions"]["price"]["value"]
    assert pack["as_of"] == "2026-10-24"


def test_fact_pack_introduces_no_new_numbers():
    """事实包不得引入决策里没有的数字(否则就是"另算")"""

    def numbers(obj) -> set[float]:
        out: set[float] = set()
        if isinstance(obj, dict):
            for v in obj.values():
                out |= numbers(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                out |= numbers(v)
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            out.add(float(obj))
        return out

    decision = _decision()
    pack = build_fact_pack(decision)
    extra = numbers(pack) - numbers(decision)
    assert extra <= {0.0, 1.0}, f"事实包引入了新数字:{sorted(extra)}"


def test_fact_pack_keeps_degraded():
    pack = build_fact_pack(_decision())
    assert pack["degraded"] == ["费用设置未启用,费用按默认档估算"]


def test_fact_pack_is_json_serializable():
    pack = build_fact_pack(_decision())
    assert json.loads(json.dumps(pack, ensure_ascii=False))["stock_code"] == "002185.SZ"


# ---------------------------------------------------------------- 规则白话

def test_rule_advice_always_has_headline():
    advice = compose_rule_advice(build_fact_pack(_decision()))
    assert advice["headline"]
    assert isinstance(advice["bullets"], list)


def test_rule_advice_survives_completely_empty_decision():
    """决策全空 → 也要给出可读文案(卡片永不空白)"""
    advice = compose_rule_advice(build_fact_pack({}))
    assert advice["headline"]
    assert advice["headline"] != ""


def test_rule_advice_mentions_grid_reason():
    advice = compose_rule_advice(build_fact_pack(_decision()))
    text = " ".join(advice["bullets"])
    assert "网格" in text
    assert "越买越套" in text


def test_rule_advice_mentions_grid_config_when_suitable():
    grid = {
        "suitable": True, "mode": "base",
        "range_low": 24.1, "range_high": 26.4, "grids": 4,
        "net_profit_per_grid": 95.0, "cash_needed": 10000.0,
    }
    advice = compose_rule_advice(build_fact_pack(_decision(grid_plan=grid)))
    text = " ".join(advice["bullets"])
    assert "网格可配置" in text
    assert "底仓模式" in text
    assert "95.0" in text


def test_rule_advice_bullets_are_capped_at_three():
    advice = compose_rule_advice(build_fact_pack(_decision()))
    assert len(advice["bullets"]) <= 3


def test_rule_advice_never_promises_return():
    advice = compose_rule_advice(build_fact_pack(_decision()))
    text = advice["headline"] + " ".join(advice["bullets"])
    for word in ("必赚", "稳赚", "保证收益", "预计收益"):
        assert word not in text


# ---------------------------------------------------------------- LLM 降级

class _FakeLLM:
    """最小 LLM 替身:只实现 chat(system, user, max_tokens)"""

    def __init__(self, payload: str | None = None, delay: float = 0.0):
        self.payload = payload
        self.delay = delay
        self.calls = 0

    async def chat(self, system: str, user: str, max_tokens: int | None = None) -> str:
        self.calls += 1
        if self.delay:
            import asyncio
            await asyncio.sleep(self.delay)
        return self.payload or "{}"


@pytest.mark.asyncio
async def test_build_advice_falls_back_to_rule_when_llm_unavailable(monkeypatch):
    async def _no_llm():
        return None
    monkeypatch.setattr(svc, "_get_llm", _no_llm)
    clear_advice_cache()

    payload = await build_advice("002185.SZ", _decision(), use_llm=True)
    assert payload["advice"]["source"] == "rule"
    assert payload["advice"]["headline"]
    assert any("规则文案" in d for d in payload["degraded"])


@pytest.mark.asyncio
async def test_build_advice_uses_llm_result(monkeypatch):
    fake = _FakeLLM(json.dumps({
        "headline": "先别动,等信号",
        "bullets": ["跌破 13.20 元止损", "涨到 19.16 元再减"],
    }, ensure_ascii=False))

    async def _fake_llm():
        return fake
    monkeypatch.setattr(svc, "_get_llm", _fake_llm)
    clear_advice_cache()

    payload = await build_advice("002185.SZ", _decision(), use_llm=True)
    assert payload["advice"]["source"] == "llm"
    assert payload["advice"]["headline"] == "先别动,等信号"
    assert len(payload["advice"]["bullets"]) == 2


@pytest.mark.asyncio
async def test_build_advice_llm_timeout_falls_back(monkeypatch):
    fake = _FakeLLM("{}", delay=5)

    async def _slow_llm():
        return fake
    monkeypatch.setattr(svc, "_get_llm", _slow_llm)
    monkeypatch.setattr(svc, "LLM_ADVICE_BUDGET", 0.05)
    clear_advice_cache()

    payload = await build_advice("002185.SZ", _decision(), use_llm=True)
    assert payload["advice"]["source"] == "rule"


@pytest.mark.asyncio
async def test_build_advice_does_not_mutate_decision(monkeypatch):
    """LLM 只翻译:决策与事实包不得被白话改写"""
    fake = _FakeLLM(json.dumps({
        "headline": "随便说个数 99.99",
        "bullets": ["编个价位 123.45 元"],
    }, ensure_ascii=False))

    async def _fake_llm():
        return fake
    monkeypatch.setattr(svc, "_get_llm", _fake_llm)
    clear_advice_cache()

    decision = _decision()
    before = json.dumps(decision, ensure_ascii=False, sort_keys=True)
    pack_before = json.dumps(build_fact_pack(decision), ensure_ascii=False, sort_keys=True)

    await build_advice("002185.SZ", decision, use_llm=True)

    assert json.dumps(decision, ensure_ascii=False, sort_keys=True) == before
    assert json.dumps(build_fact_pack(decision), ensure_ascii=False, sort_keys=True) == pack_before


@pytest.mark.asyncio
async def test_build_advice_result_shape():
    payload = await build_advice("002185.SZ", _decision(), use_llm=False)
    assert set(payload.keys()) == {"advice", "degraded"}
    assert set(payload["advice"].keys()) == {"headline", "bullets", "source", "generated_at"}
    assert payload["advice"]["source"] == "rule"


@pytest.mark.asyncio
async def test_build_advice_cache_hit_avoids_second_llm_call(monkeypatch):
    fake = _FakeLLM(json.dumps({"headline": "缓存命中", "bullets": []}, ensure_ascii=False))

    async def _fake_llm():
        return fake
    monkeypatch.setattr(svc, "_get_llm", _fake_llm)
    clear_advice_cache()

    decision = _decision()
    await build_advice("002185.SZ", decision, use_llm=True)
    await build_advice("002185.SZ", decision, use_llm=True)
    assert fake.calls == 1


# ---------------------------------------------------------------- 提示词

def test_system_prompt_forbids_inventing_numbers():
    system = svc.DECISION_ADVICE_SYSTEM
    assert "唯一真相源" in system
    assert "不得改写" in system
    assert "不承诺收益" in system
