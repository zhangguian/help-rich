"""多智能体分析测试(阶段4)。

重点覆盖**鲁棒性**而非 LLM 输出质量:
- JSON 解析容错(LLM 常带解释文字/围栏)
- Agent 失败降级(不给用户 500)
- PM 给出非法动作时保守回落
- 无 LLM 时仍返回可用报告
"""
import asyncio

import pytest

from app.modules.analysis.contracts import (
    ACTION_LABELS,
    ROLE_LABELS,
    AgentOpinion,
    AgentRole,
    DecisionReport,
    Stance,
)
from app.modules.analysis.prompts import (
    build_bear_prompt,
    build_bull_prompt,
    build_pm_prompt,
    build_risk_prompt,
    build_role_prompt,
)
from app.modules.analysis.service import MultiAgentService, parse_json_reply


class TestParseJsonReply:
    def test_plain_json(self):
        assert parse_json_reply('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        text = '```json\n{"stance": "bullish"}\n```'
        assert parse_json_reply(text) == {"stance": "bullish"}

    def test_fenced_without_language(self):
        text = '```\n{"stance": "bearish"}\n```'
        assert parse_json_reply(text) == {"stance": "bearish"}

    def test_json_with_surrounding_prose(self):
        text = '好的,我的分析如下:\n{"stance": "neutral", "confidence": 0.5}\n以上。'
        assert parse_json_reply(text)["stance"] == "neutral"

    def test_empty_string(self):
        assert parse_json_reply("") == {}

    def test_garbage(self):
        assert parse_json_reply("完全不是 JSON") == {}

    def test_json_array_not_dict(self):
        """返回数组时应判为不可解析(不是 dict)。"""
        assert parse_json_reply("[1,2,3]") == {}


class TestContracts:
    def test_all_roles_have_labels(self):
        for role in (
            AgentRole.TECHNICAL, AgentRole.FUND_FLOW, AgentRole.NEWS,
            AgentRole.FUNDAMENTAL, AgentRole.BULL, AgentRole.BEAR,
            AgentRole.RISK, AgentRole.PM,
        ):
            assert role.value in ROLE_LABELS

    def test_all_actions_have_labels(self):
        for key in ("strong_buy", "buy", "hold", "reduce", "sell"):
            assert key in ACTION_LABELS

    def test_opinion_to_dict(self):
        op = AgentOpinion(role="technical", stance="bullish", confidence=0.8,
                          argument="均线多头", key_points=["MA20上穿"])
        d = op.to_dict()
        assert d["role"] == "technical"
        assert d["stance_label"] == "看多"
        assert d["confidence"] == 0.8
        assert d["degraded"] is False

    def test_report_to_dict_has_labels(self):
        r = DecisionReport(stock_code="600519.SH", action="buy")
        d = r.to_dict()
        assert d["action_label"] == "轻仓买入"
        assert "disclaimer" in d


class TestPrompts:
    def test_role_prompt_contains_facts_and_rule(self):
        system, user = build_role_prompt(
            AgentRole.TECHNICAL.value, "贵州茅台", {"ma20": 10.5, "volume_ratio": 2.1}
        )
        assert "绝不允许自己计算" in system
        assert "10.5" in user  # 事实必须传给模型
        assert "贵州茅台" in user
        assert "JSON" in user

    def test_bull_bear_prompts_include_opinions(self):
        ops = [{"role": "technical", "argument": "看多"}]
        _, u_bull = build_bull_prompt("茅台", ops, {"x": 1})
        _, u_bear = build_bear_prompt("茅台", ops, {"x": 1})
        assert "多头研究员" in u_bull
        assert "空头研究员" in u_bear
        assert "看多" in u_bull

    def test_risk_prompt_asks_for_unmentioned_risks(self):
        _, user = build_risk_prompt("茅台", {"a": 1}, {"b": 2}, {"c": 3})
        assert "风险" in user
        assert "risk_flags" in user

    def test_pm_prompt_has_decision_rules(self):
        _, user = build_pm_prompt("茅台", {}, {}, {}, {})
        assert "投资经理" in user
        assert "hold" in user
        assert "不要因为" in user  # 反从众约束


class TestDegradation:
    @pytest.mark.asyncio
    async def test_no_llm_returns_usable_report(self, monkeypatch):
        """没配 LLM Key 时不能 500,应返回可读的降级报告。"""
        svc = MultiAgentService()

        async def fake_gather(code):
            return ({"data_quality": "测试"}, "测试股", "")

        async def no_llm():
            return None

        monkeypatch.setattr(svc, "_gather_facts", fake_gather)
        monkeypatch.setattr("app.modules.analysis.service._get_llm", no_llm)

        report = await svc.analyze("600519.SH")
        assert report.degraded is True
        assert report.action == "hold"
        assert "未配置 AI 模型" in report.summary
        assert report.to_dict()["action_label"] == "持有观望"

    @pytest.mark.asyncio
    async def test_agent_timeout_degrades(self, monkeypatch):
        """单个 Agent 失败不拖垮整体。"""
        svc = MultiAgentService()

        async def fake_gather(code):
            return ({"technical": {"ma20": 1}}, "测试股", "")

        class SlowLLM:
            model_name = "test-model"

            async def chat(self, system, user_prompt, temperature=0.3):
                return '{"stance":"bullish","confidence":0.5,"argument":"x","key_points":[]}'

        async def fake_get_llm():
            return SlowLLM()

        monkeypatch.setattr(svc, "_gather_facts", fake_gather)
        monkeypatch.setattr("app.modules.analysis.service._get_llm", fake_get_llm)

        report = await svc.analyze("600519.SH")
        d = report.to_dict()
        # 分析师 + 多空 + PM 全部产出
        assert len(d["opinions"]) >= 6
        assert d["action"] in ACTION_LABELS

    @pytest.mark.asyncio
    async def test_invalid_pm_action_falls_back_to_hold(self, monkeypatch):
        """PM 返回非法动作时必须保守回落 hold,不能直接透传给前端。"""
        svc = MultiAgentService()

        async def fake_gather(code):
            return ({"technical": {}}, "测试股", "")

        class WeirdLLM:
            model_name = "weird"

            def __init__(self):
                self.n = 0

            async def chat(self, system, user_prompt, temperature=0.3):
                self.n += 1
                if "投资经理" in user_prompt:
                    return '{"action":"梭哈","confidence":0.99,"summary":"满仓"}'
                return '{"stance":"bullish","confidence":0.6,"argument":"a","key_points":["x"]}'

        async def fake_get_llm():
            return WeirdLLM()

        monkeypatch.setattr(svc, "_gather_facts", fake_gather)
        monkeypatch.setattr("app.modules.analysis.service._get_llm", fake_get_llm)

        report = await svc.analyze("600519.SH")
        assert report.action == "hold"  # 非法动作被拒

    @pytest.mark.asyncio
    async def test_garbage_llm_output_degrades(self, monkeypatch):
        """LLM 返回非 JSON 时应降级而不是崩溃。"""
        svc = MultiAgentService()

        async def fake_gather(code):
            return ({"technical": {}}, "测试股", "")

        class JunkLLM:
            model_name = "junk"

            async def chat(self, system, user_prompt, temperature=0.3):
                return "我不知道该说什么"

        async def fake_get_llm():
            return JunkLLM()

        monkeypatch.setattr(svc, "_gather_facts", fake_gather)
        monkeypatch.setattr("app.modules.analysis.service._get_llm", fake_get_llm)

        report = await svc.analyze("600519.SH")
        d = report.to_dict()
        assert d["action"] in ACTION_LABELS  # 回落 hold
        assert any(o["degraded"] for o in d["opinions"])


class TestFullFlow:
    @pytest.mark.asyncio
    async def test_complete_debate_flow(self, monkeypatch):
        """完整链路:4 分析师 + 多空 + 风控 + PM。"""
        svc = MultiAgentService()

        async def fake_gather(code):
            return (
                {
                    "technical": {"ma20": 10.0, "volume_ratio": 2.0},
                    "fund_flow": {"main_net_inflow": "1.2亿"},
                    "news": {"news": [{"title": "利好"}]},
                    "fundamental": {"pe": 22},
                    "key_levels": {"support": [9.5], "resistance": [11.0]},
                },
                "测试股",
                "",
            )

        class GoodLLM:
            model_name = "good-model"

            async def chat(self, system, user_prompt, temperature=0.3):
                if "投资经理" in user_prompt:
                    return (
                        '{"action":"buy","confidence":0.72,'
                        '"summary":"资金与技术面共振,风险可控。","key_points":["量能放大"]}'
                    )
                if "风控经理" in user_prompt:
                    return (
                        '{"argument":"需注意估值偏高。",'
                        '"risk_flags":["估值风险","流动性"],"key_points":[]}'
                    )
                return (
                    '{"stance":"bullish","confidence":0.66,'
                    '"argument":"均线多头排列且资金流入。","key_points":["MA20上穿","主力净流入"]}'
                )

        async def fake_get_llm():
            return GoodLLM()

        monkeypatch.setattr(svc, "_gather_facts", fake_gather)
        monkeypatch.setattr("app.modules.analysis.service._get_llm", fake_get_llm)

        report = await svc.analyze("600519.SH")
        d = report.to_dict()

        assert d["stock_code"] == "600519.SH"
        assert d["stock_name"] == "测试股"
        assert d["model"] == "good-model"
        assert d["action"] == "buy"
        assert d["confidence"] == pytest.approx(0.72)
        assert len(d["risk_flags"]) == 2
        assert d["key_levels"]["support"] == [9.5]
        assert d["degraded"] is False
        # 6 个视角:4 分析师 + 多 + 空
        assert len(d["opinions"]) == 6
        roles = [o["role"] for o in d["opinions"]]
        assert AgentRole.TECHNICAL.value in roles
        assert AgentRole.BULL.value in roles
        assert AgentRole.BEAR.value in roles
        # 每条 opinion 都有中文标签
        assert all(o["label"] for o in d["opinions"])

    @pytest.mark.asyncio
    async def test_facts_failure_still_works(self, monkeypatch):
        """事实收集失败(无 K 线)时,Agent 仍应看到 data_quality 并正常返回。"""
        svc = MultiAgentService()

        async def failing_gather(code):
            return (
                {
                    "technical": {"data_quality": "数据不足:无K线"},
                    "fund_flow": {"data_quality": "数据不足"},
                    "news": {"data_quality": "数据不足"},
                },
                code,
                "技术面:无 K 线数据",
            )

        class L:
            model_name = "m"

            async def chat(self, system, user_prompt, temperature=0.3):
                if "投资经理" in user_prompt:
                    return '{"action":"hold","confidence":0.2,"summary":"数据不足,建议观望。","key_points":[]}'
                return '{"stance":"neutral","confidence":0.2,"argument":"数据不足","key_points":["无法判断"]}'

        async def fake_get_llm():
            return L()

        monkeypatch.setattr(svc, "_gather_facts", failing_gather)
        monkeypatch.setattr("app.modules.analysis.service._get_llm", fake_get_llm)

        report = await svc.analyze("000001.SZ")
        assert report.action == "hold"
