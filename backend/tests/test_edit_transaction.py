"""编辑已录入的流水:改方向(买↔卖)/ 股数 / 价格

背景(用户报):
  「159599.SZ 我录错了,应该是卖出的」—— 以前**改不了方向**,
  只能删掉重录(丢评分快照 + 要重新输一遍 + 补T清单要等重新录完才出现)。
  「怎么有些没有名称?」—— 挂单的名称取自**流水**,而从持仓侧录的流水
  往往没带名称 → 清单里显示「—」,但持仓行是有名字的。

本文件把这两条钉死:
  1. 改方向:允许,且必须**先验算整条链是否自洽**(卖不出那么多股 → 422 拒写);
  2. 改方向后:持仓股数/摊薄总额/已实现盈亏/补T清单分组,全部跟着重算;
  3. 名称回退:流水没名字 → 用**持仓行**的名字;两边都没 → null(不编)。
"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import async_session
from app.main import app
from app.models.orm import Position as PositionRow
from app.services.diagnose_service import diagnose_service


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_quote(monkeypatch):
    import app.services.quote_service as qs

    class _Boom:
        async def get_quotes(self, codes):
            raise RuntimeError("行情源不可用")

    monkeypatch.setattr(qs, "get_quote_service", lambda: _Boom())


@pytest.fixture(autouse=True)
def _no_diagnose(monkeypatch):
    async def _noop(_tx_id):
        return None

    monkeypatch.setattr(diagnose_service, "score_and_notify", _noop)


def _seed_position(code: str, shares: int, total_cost: str, name: str = "测试股"):
    """建持仓基准(摊薄总额 = 净投入)。"""

    async def _do():
        async with async_session() as session:
            session.add(
                PositionRow(
                    account_id=1,
                    stock_code=code,
                    stock_name=name,
                    shares=shares,
                    total_cost=total_cost,
                    realized_pnl="0.00",
                    base_shares=shares,
                    base_total_cost=total_cost,
                    base_realized_pnl="0.00",
                    base_tx_id=0,
                )
            )
            await session.commit()

    asyncio.run(_do())


def _post(client, code, action, shares, price, d, t=None, name="测试股"):
    body = {
        "stock_code": code,
        "action": action,
        "shares": shares,
        "price": price,
        "trade_date": d,
    }
    if name is not None:
        body["stock_name"] = name
    if t:
        body["trade_time"] = t
    return client.post("/api/transactions", json=body)


def _position(client, code):
    for p in client.get("/api/positions").json()["items"]:
        if p["stock_code"] == code:
            return p
    return None


def _pending(client):
    body = client.get("/api/t-reminders/pending").json()
    return body["items"], body["forward_items"]


class TestEditTransactionAction:
    """改方向(买 ↔ 卖)"""

    def test_buy_to_sell_flips_position(self, client):
        """基准 1000 股 / 15000.00;把「买入 100@12」改成卖出 → 股数 900、净投入 13800

        摊薄口径:卖出按**成交价**回收净投入 → 15000 − 100×12 = 13800。
        已实现盈亏 = (12 − 摊薄成本 15) × 100 = −300。
        """
        code = "600519.SH"
        _seed_position(code, 1000, "15000.00")

        r = _post(client, code, "buy", 100, "12.000", "2026-11-04", "10:00")
        assert r.status_code == 201
        tx_id = r.json()["id"]

        pos = _position(client, code)
        assert pos["shares"] == 1100
        assert float(pos["total_cost"]) == pytest.approx(16200.00, abs=0.01)

        # 改成卖出
        r = client.patch(f"/api/transactions/{tx_id}", json={"action": "sell"})
        assert r.status_code == 200, r.text
        assert r.json()["action"] == "sell"

        pos = _position(client, code)
        assert pos["shares"] == 900
        assert float(pos["total_cost"]) == pytest.approx(13800.00, abs=0.01)
        assert float(pos["realized_pnl"]) == pytest.approx(-300.00, abs=0.01)

    def test_sell_to_buy_flips_position(self, client):
        """把「卖出 100@16」改成买入 → 股数 +100、净投入 +1600"""
        code = "600519.SH"
        _seed_position(code, 1000, "15000.00")

        r = _post(client, code, "sell", 100, "16.000", "2026-11-04", "10:00")
        tx_id = r.json()["id"]

        r = client.patch(f"/api/transactions/{tx_id}", json={"action": "buy"})
        assert r.status_code == 200, r.text

        pos = _position(client, code)
        assert pos["shares"] == 1100
        assert float(pos["total_cost"]) == pytest.approx(16600.00, abs=0.01)
        # 已实现盈亏归零(方向反了,原来的卖出已实现不再成立)
        assert float(pos["realized_pnl"]) == pytest.approx(0.00, abs=0.01)

    def test_change_to_sell_beyond_holdings_is_rejected(self, client):
        """改成卖出但股数不够 → 422 拒绝写入,**持仓不受影响**

        这是改方向的安全网:卖出超额会让整条链不自洽 → 必须挡住。
        (基准 1000 股 → 改成卖出 1500 股才超额;卖 500 股是合法的,别写错)
        """
        code = "600519.SH"
        _seed_position(code, 1000, "15000.00")

        # 买入 100 → 1100 股;改成卖出 1500 股 → 卖出超额
        r = _post(client, code, "buy", 100, "12.000", "2026-11-04", "10:00")
        tx_id = r.json()["id"]

        r = client.patch(
            f"/api/transactions/{tx_id}", json={"action": "sell", "shares": 1500}
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "CHAIN_INVALID"

        # 持仓没被动过
        pos = _position(client, code)
        assert pos["shares"] == 1100
        assert float(pos["total_cost"]) == pytest.approx(16200.00, abs=0.01)

    def test_direction_change_moves_t_list_group(self, client):
        """方向改了 → 补T清单的分组也跟着换(反T ↔ 正T)

        用户场景:「买」录成了「卖」→ 这笔本来该是**待接回**(反T),
        录错后却显示在**待卖出**(正T)。改完方向必须换组。
        """
        code = "600519.SH"
        _seed_position(code, 1000, "15000.00")

        r = _post(client, code, "buy", 100, "12.000", "2026-11-04", "10:00")
        tx_id = r.json()["id"]

        reverse, forward = _pending(client)
        assert [x["stock_code"] for x in forward] == [code]  # 先买后卖 → 正T
        assert reverse == []

        client.patch(f"/api/transactions/{tx_id}", json={"action": "sell"})

        reverse, forward = _pending(client)
        assert [x["stock_code"] for x in reverse] == [code]  # 先卖后买 → 反T
        assert forward == []

    def test_patch_cannot_change_stock_code_or_date(self, client):
        """不能改股票代码 / 交易日 —— 改标的等于把流水搬到别的股票上"""
        code = "600519.SH"
        _seed_position(code, 1000, "15000.00")
        r = _post(client, code, "buy", 100, "12.000", "2026-11-04", "10:00")
        tx_id = r.json()["id"]

        # 多传一个 stock_code / trade_date → 契约里没有这两个字段 → 忽略,不改
        client.patch(
            f"/api/transactions/{tx_id}",
            json={"stock_code": "000001.SZ", "trade_date": "2026-01-01"},
        )
        after = client.get("/api/transactions?stock_code=600519.SH").json()["items"]
        assert len(after) == 1
        assert after[0]["stock_code"] == code
        assert after[0]["trade_date"] == "2026-11-04"


class TestTListNameFallback:
    """清单名称:流水没名字 → 用持仓行的名字"""

    def test_name_falls_back_to_position(self, client):
        """流水没带名称 → 清单显示持仓行的名字(不是「—」)"""
        code = "600519.SH"
        _seed_position(code, 1000, "15000.00", name="贵州茅台")

        # 流水**不带**名称(从持仓侧录的典型情况)
        r = _post(client, code, "sell", 100, "16.000", "2026-11-04", "10:00", name=None)
        assert r.status_code == 201
        assert r.json()["stock_name"] is None

        reverse, _ = _pending(client)
        assert len(reverse) == 1
        assert reverse[0]["stock_name"] == "贵州茅台"

    def test_name_prefers_transaction_over_position(self, client):
        """流水带了名称 → 用流水的(流水更新鲜)"""
        code = "600519.SH"
        _seed_position(code, 1000, "15000.00", name="旧名称")

        _post(client, code, "sell", 100, "16.000", "2026-11-04", "10:00", name="新名称")

        reverse, _ = _pending(client)
        assert reverse[0]["stock_name"] == "新名称"

    def test_no_name_anywhere_stays_null(self, client):
        """两边都没名称 → null(不编名字)"""
        code = "600519.SH"

        async def _do():
            async with async_session() as session:
                session.add(
                    PositionRow(
                        account_id=1,
                        stock_code=code,
                        stock_name=None,
                        shares=1000,
                        total_cost="15000.00",
                        realized_pnl="0.00",
                        base_shares=1000,
                        base_total_cost="15000.00",
                        base_realized_pnl="0.00",
                        base_tx_id=0,
                    )
                )
                await session.commit()

        asyncio.run(_do())
        _post(client, code, "sell", 100, "16.000", "2026-11-04", "10:00", name=None)

        reverse, _ = _pending(client)
        assert reverse[0]["stock_name"] is None


class TestTListOpenTxIds:
    """挂单要能定位到「组成它的开腿流水」—— 前端编辑入口靠它"""

    def test_open_tx_ids_point_to_open_leg(self, client):
        """反T 挂单 → open_tx_ids 里是那笔**卖出**的流水 id"""
        code = "600519.SH"
        _seed_position(code, 1000, "15000.00")

        r = _post(client, code, "sell", 100, "16.000", "2026-11-04", "10:00")
        sell_id = r.json()["id"]
        # 再买回 → 挂单闭合,不再出现在清单里
        _post(client, code, "buy", 100, "15.000", "2026-11-04", "14:00")

        reverse, _ = _pending(client)
        assert reverse == []

        # 再开一笔 → 新的挂单,指向新的卖出
        r2 = _post(client, code, "sell", 100, "16.500", "2026-11-04", "14:30")
        reverse, _ = _pending(client)
        assert len(reverse) == 1
        assert reverse[0]["open_tx_ids"] == [r2.json()["id"]]
        assert sell_id != r2.json()["id"]

    def test_multiple_legs_aggregate_into_one_row(self, client):
        """同一只票做了两次反T → 清单里合并成一行,open_tx_ids 有两个 id"""
        code = "600519.SH"
        _seed_position(code, 1000, "15000.00")

        r1 = _post(client, code, "sell", 100, "16.000", "2026-11-04", "10:00")
        r2 = _post(client, code, "sell", 100, "17.000", "2026-11-04", "13:00")

        reverse, _ = _pending(client)
        assert len(reverse) == 1  # 合并成一行
        assert reverse[0]["shares"] == 200
        assert reverse[0]["open_tx_ids"] == sorted([r1.json()["id"], r2.json()["id"]])
