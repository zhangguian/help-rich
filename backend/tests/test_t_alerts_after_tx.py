"""录流水后**立刻**对齐做T提醒(POST / PATCH / DELETE /api/transactions 内的同步)

缺口背景(为什么要有这个文件):
  `sync_auto_alerts` 原先只挂在 `GET /api/t-reminders/pending` 上。
  用户的做T节奏是「先录第一次做T(开腿)→ 等第二腿的提醒」——
  如果录完开腿就关掉页面,第二腿的到价 + 预警提醒**永远不会被建出来**,
  价格到了也不会响。状态流转不能只挂在前端副作用上。

所以这里全部断言「不打开补T清单页,只靠录入这一个动作」:
  1. 录第一腿 → 到价提醒 + 预警提醒立刻存在;
  2. 录第二腿(接回 / 卖出)→ 挂单闭合,对应提醒立刻停用;
  3. 只同步**本标的** —— 别的标的的自动提醒不能被误停用(scope 的意义);
  4. 删掉闭合腿 → 挂单重新出现 → 提醒建回来;
  5. 改第一腿价格 → 基准线变了 → 提醒就地跟到新的一档。

⚠️ 全程不调 `/api/t-reminders/pending`:调了就等于用「打开页面」掩盖了缺口。
"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import async_session
from app.main import app
from app.models.orm import Position as PositionRow
from app.services.diagnose_service import diagnose_service

AUTO = "[做T]"
PRE = "[做T·预警]"


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_quote(monkeypatch):
    """行情不可用 → 现价留 null(不编数字,也不会去连真实行情源)。"""
    import app.services.quote_service as qs

    class _Boom:
        async def get_quotes(self, codes):
            raise RuntimeError("行情源不可用")

    monkeypatch.setattr(qs, "get_quote_service", lambda: _Boom())


@pytest.fixture(autouse=True)
def _no_diagnose(monkeypatch):
    """录入后的诊断(评分 + LLM 评语)与本次改动无关,替换成空操作。"""

    async def _noop(_tx_id):
        return None

    monkeypatch.setattr(diagnose_service, "score_and_notify", _noop)


def _post_tx(
    client: TestClient,
    code: str,
    action: str,
    shares: int,
    price: str,
    trade_date: str,
):
    return client.post(
        "/api/transactions",
        json={
            "stock_code": code,
            "action": action,
            "shares": shares,
            "price": price,
            "trade_date": trade_date,
            "stock_name": "测试股",
        },
    )


def _seed_position(code: str, shares: int, total_cost: str):
    """建持仓行 → 允许后续 POST 卖出(卖出额度按持仓判定)。"""

    async def _do():
        async with async_session() as session:
            session.add(
                PositionRow(
                    account_id=1,
                    stock_code=code,
                    stock_name="测试股",
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


def _alerts(client: TestClient) -> list[dict]:
    return client.get("/api/price-alerts").json()["items"]


def _by_prefix(client: TestClient, prefix: str) -> list[dict]:
    return [a for a in _alerts(client) if (a.get("name") or "").startswith(prefix)]


def _leaf(alert: dict) -> dict:
    return alert["conditions"]["conditions"][0]


def _manual_alert(
    client: TestClient, code: str, op: str, value: float, name: str = "明日补T接回"
) -> int:
    r = client.post(
        "/api/price-alerts",
        json={
            "stock_code": code,
            "name": name,
            "conditions": {
                "op": "and",
                "conditions": [{"metric": "price", "op": op, "value": value}],
            },
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _claimed(alert: dict) -> bool:
    return alert["conditions"].get("claimed") is True


class TestFirstLegCreatesAlerts:
    """录第一腿(开腿)→ 立刻建出第二腿的到价 + 预警提醒"""

    def test_forward_first_leg_creates_both_alerts(self, client):
        """正T开腿(先买后卖):买入即建「涨到就提醒卖出」+ 预警"""
        r = _post_tx(client, "600519.SH", "buy", 100, "10.500", "2026-11-03")
        assert r.status_code == 201, r.text

        auto = _by_prefix(client, AUTO)
        assert len(auto) == 1
        assert auto[0]["enabled"] is True
        assert auto[0]["stock_code"] == "600519.SH"
        assert _leaf(auto[0])["op"] == ">="
        assert _leaf(auto[0])["value"] == pytest.approx(10.605)

        pre = _by_prefix(client, PRE)
        assert len(pre) == 1
        assert pre[0]["enabled"] is True
        assert _leaf(pre[0])["op"] == ">="
        # 预警线 = 到价线朝基准线方向再退 1% = 10.605 × 0.99 = 10.499
        assert _leaf(pre[0])["value"] == pytest.approx(10.499, abs=1e-3)

    def test_reverse_first_leg_creates_both_alerts(self, client):
        """反T开腿(先卖后买):卖出即建「跌到就提醒接回」+ 预警"""
        _seed_position("600519.SH", shares=400, total_cost="6231.20")
        r = _post_tx(client, "600519.SH", "sell", 100, "10.500", "2026-11-02")
        assert r.status_code == 201, r.text

        auto = _by_prefix(client, AUTO)
        assert len(auto) == 1
        assert auto[0]["enabled"] is True
        assert _leaf(auto[0])["op"] == "<="
        assert _leaf(auto[0])["value"] == pytest.approx(10.395)

        pre = _by_prefix(client, PRE)
        assert len(pre) == 1
        assert pre[0]["enabled"] is True
        assert _leaf(pre[0])["op"] == "<="
        # 反T 预警线往上退:10.395 × 1.01 = 10.499
        assert _leaf(pre[0])["value"] == pytest.approx(10.499, abs=1e-3)


class TestSecondLegDisablesAlerts:
    """录第二腿 → 挂单闭合 → 对应提醒立刻停用(不是删除)"""

    def test_forward_second_leg_disables_both_alerts(self, client):
        assert (
            _post_tx(client, "600519.SH", "buy", 100, "10.500", "2026-11-03").status_code
            == 201
        )
        auto_id = _by_prefix(client, AUTO)[0]["id"]
        pre_id = _by_prefix(client, PRE)[0]["id"]

        # 同一天卖出接回(做T完成)—— 不需要打开补T清单页
        r = _post_tx(client, "600519.SH", "sell", 100, "10.600", "2026-11-03")
        assert r.status_code == 201, r.text

        alerts = {a["id"]: a for a in _alerts(client)}
        assert alerts[auto_id]["enabled"] is False
        assert alerts[pre_id]["enabled"] is False
        # 停用不是删除 —— 触发历史还要留着
        assert auto_id in alerts
        assert pre_id in alerts

    def test_reverse_second_leg_disables_both_alerts(self, client):
        _seed_position("600519.SH", shares=400, total_cost="6231.20")
        assert (
            _post_tx(client, "600519.SH", "sell", 100, "10.500", "2026-11-02").status_code
            == 201
        )
        auto_id = _by_prefix(client, AUTO)[0]["id"]
        pre_id = _by_prefix(client, PRE)[0]["id"]

        r = _post_tx(client, "600519.SH", "buy", 100, "10.100", "2026-11-03")
        assert r.status_code == 201, r.text

        alerts = {a["id"]: a for a in _alerts(client)}
        assert alerts[auto_id]["enabled"] is False
        assert alerts[pre_id]["enabled"] is False


class TestScopeIsolation:
    """只同步本标的 —— 别家标的的自动提醒不能被误停用

    这是 `scope_codes` 存在的理由:同步时传的是**部分**挂单,
    若不加作用域,不在本次 items 里的自动提醒会被当成「挂单已消失」全部停掉。
    """

    def test_other_stock_alerts_untouched(self, client):
        assert (
            _post_tx(client, "600519.SH", "buy", 100, "10.500", "2026-11-03").status_code
            == 201
        )
        first = _by_prefix(client, AUTO)
        assert len(first) == 1
        first_id = first[0]["id"]

        # 另一只票开腿 —— 这一步会触发一次同步,绝不能碰 600519 的提醒
        assert (
            _post_tx(client, "000001.SZ", "buy", 200, "5.000", "2026-11-03").status_code
            == 201
        )

        alerts = {a["id"]: a for a in _alerts(client)}
        assert alerts[first_id]["enabled"] is True
        # 两只票各有一条到价提醒
        assert {a["stock_code"] for a in _by_prefix(client, AUTO)} == {
            "600519.SH",
            "000001.SZ",
        }

    def test_closing_one_stock_does_not_disable_another(self, client):
        """A 闭合只停 A 的提醒,B 的提醒必须还启用"""
        assert (
            _post_tx(client, "600519.SH", "buy", 100, "10.500", "2026-11-03").status_code
            == 201
        )
        assert (
            _post_tx(client, "000001.SZ", "buy", 200, "5.000", "2026-11-03").status_code
            == 201
        )
        b_ids = [a["id"] for a in _by_prefix(client, AUTO) if a["stock_code"] == "000001.SZ"]
        assert len(b_ids) == 1

        # A 卖出闭合
        assert (
            _post_tx(client, "600519.SH", "sell", 100, "10.600", "2026-11-03").status_code
            == 201
        )

        alerts = {a["id"]: a for a in _alerts(client)}
        for aid in b_ids:
            assert alerts[aid]["enabled"] is True


class TestClaimedManualAlertAfterTx:
    """被清单认领过的**手工**提醒,同样要随录入即时停用

    用户的真实痛点:手工建了「明日补T接回」,它被复用成某条挂单的到价提醒;
    做T闭合后这条提醒还天天响(真实数据里触发过 313 次)。
    认领关系落在条件树顶层 `claimed` 标记上,所以停用不依赖打开清单页。
    """

    def test_second_leg_disables_claimed_manual_alert(self, client):
        """录第二腿(接回)→ 被认领的手工提醒立刻停用,并撤掉认领标记"""
        _seed_position("600519.SH", shares=400, total_cost="6231.20")
        # 先手工建提醒,价格正好落在一档价(10.500 × 0.99 = 10.395)
        manual_id = _manual_alert(client, "600519.SH", "<=", 10.395)

        assert (
            _post_tx(client, "600519.SH", "sell", 100, "10.500", "2026-11-02").status_code
            == 201
        )
        alerts = {a["id"]: a for a in _alerts(client)}
        # 复用手工那条(没有另外建自动提醒),并且已认领
        assert not _by_prefix(client, AUTO)
        assert alerts[manual_id]["enabled"] is True
        assert _claimed(alerts[manual_id]) is True

        # 接回 → 做T闭合,不需要打开补T清单页
        assert (
            _post_tx(client, "600519.SH", "buy", 100, "10.100", "2026-11-03").status_code
            == 201
        )
        alert = {a["id"]: a for a in _alerts(client)}[manual_id]
        assert alert["enabled"] is False
        assert _claimed(alert) is False, "认领标记必须撤掉,否则用户再也开不起来"

    def test_claimed_alert_of_other_stock_untouched(self, client):
        """A 闭合只停 A 的被认领提醒,B 的被认领提醒必须还启用"""
        _seed_position("600519.SH", shares=400, total_cost="6231.20")
        a_id = _manual_alert(client, "600519.SH", "<=", 10.395)
        b_id = _manual_alert(client, "000001.SZ", ">=", 5.05)
        assert (
            _post_tx(client, "600519.SH", "sell", 100, "10.500", "2026-11-02").status_code
            == 201
        )
        assert (
            _post_tx(client, "000001.SZ", "buy", 200, "5.000", "2026-11-03").status_code
            == 201
        )
        alerts = {a["id"]: a for a in _alerts(client)}
        assert _claimed(alerts[a_id]) is True
        assert _claimed(alerts[b_id]) is True

        # A 接回闭合 —— 同步只作用于 600519.SH
        assert (
            _post_tx(client, "600519.SH", "buy", 100, "10.100", "2026-11-03").status_code
            == 201
        )
        alerts = {a["id"]: a for a in _alerts(client)}
        assert alerts[a_id]["enabled"] is False
        assert alerts[b_id]["enabled"] is True
        assert _claimed(alerts[b_id]) is True


class TestUpdateAndDelete:
    """改 / 删流水同样要即时对齐(挂单状态会变)"""

    def test_deleting_closing_leg_recreates_alert(self, client):
        """删掉闭合腿 → 挂单重新出现 → 提醒重新建出来(原来的已停用)"""
        assert (
            _post_tx(client, "600519.SH", "buy", 100, "10.500", "2026-11-03").status_code
            == 201
        )
        close = _post_tx(client, "600519.SH", "sell", 100, "10.600", "2026-11-03")
        assert close.status_code == 201
        assert all(a["enabled"] is False for a in _by_prefix(client, AUTO))

        r = client.delete(f"/api/transactions/{close.json()['id']}")
        assert r.status_code == 204, r.text

        enabled = [a for a in _by_prefix(client, AUTO) if a["enabled"]]
        assert len(enabled) == 1
        assert _leaf(enabled[0])["op"] == ">="
        assert _leaf(enabled[0])["value"] == pytest.approx(10.605)

    def test_updating_first_leg_realigns_alert(self, client):
        """改第一腿价格 → 基准线变了 → 提醒**就地**跟到新的一档(不新建)"""
        created = _post_tx(client, "600519.SH", "buy", 100, "10.500", "2026-11-03")
        assert created.status_code == 201
        first = _by_prefix(client, AUTO)[0]
        assert _leaf(first)["value"] == pytest.approx(10.605)

        r = client.patch(
            f"/api/transactions/{created.json()['id']}", json={"price": "12.000"}
        )
        assert r.status_code == 200, r.text

        autos = _by_prefix(client, AUTO)
        assert len(autos) == 1
        # 同一条提醒就地改价:新一档 = 12.000 × 1.01 = 12.120
        assert autos[0]["id"] == first["id"]
        assert autos[0]["enabled"] is True
        assert _leaf(autos[0])["value"] == pytest.approx(12.120)


class TestNoPendingNoAlert:
    """没有挂单就不该留下启用的自动提醒"""

    def test_closed_t_leaves_no_enabled_alert(self, client):
        assert (
            _post_tx(client, "600519.SH", "buy", 100, "10.500", "2026-11-03").status_code
            == 201
        )
        assert (
            _post_tx(client, "600519.SH", "sell", 100, "10.600", "2026-11-03").status_code
            == 201
        )
        assert [a for a in _by_prefix(client, AUTO) if a["enabled"]] == []
        assert [a for a in _by_prefix(client, PRE) if a["enabled"]] == []

    def test_plain_buy_leg_is_not_a_closed_t(self, client):
        """一笔普通买入(还在窗口内)就是正T挂单 → 提醒必须存在

        对照组:确认上面那条「闭合就停用」没把门禁修过头 ——
        真的还有挂单时提醒照样要建。
        """
        assert (
            _post_tx(client, "600519.SH", "buy", 100, "10.500", "2026-11-03").status_code
            == 201
        )
        assert len([a for a in _by_prefix(client, AUTO) if a["enabled"]]) == 1
        assert len([a for a in _by_prefix(client, PRE) if a["enabled"]]) == 1
