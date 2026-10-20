"""P6.1 年账单后端测试

- annual_report_service.get_annual_report(year):聚合胜率/Top5/净盈亏
- 边界:全年无交易 / 全胜 / 全败 / 跨年持仓
- API GET /api/annual-report/{year}
"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.portfolio.repository import transaction_repo
from app.services.annual_report_service import get_annual_report


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    from app.db import async_session
    from app.models.orm import Position, Transaction
    from sqlalchemy import delete

    async def _do():
        async with async_session() as session:
            await session.execute(delete(Transaction))
            await session.execute(delete(Position))
            await session.commit()

    asyncio.run(_do())
    yield


async def _seed_year_2026():
    """2026 年:600519 买入 1000@10 卖出 500@15(赚)+ 000001 买入 200@20 卖出 200@10(亏)"""
    await transaction_repo.create(
        stock_code="600519.SH", stock_name="A", action="buy",
        shares=1000, price="10.000", trade_date=date(2026, 3, 1),
    )
    await transaction_repo.create(
        stock_code="000001.SZ", stock_name="B", action="buy",
        shares=200, price="20.000", trade_date=date(2026, 5, 1),
    )
    await transaction_repo.create(
        stock_code="600519.SH", stock_name="A", action="sell",
        shares=500, price="15.000", trade_date=date(2026, 6, 1),
    )
    await transaction_repo.create(
        stock_code="000001.SZ", stock_name="B", action="sell",
        shares=200, price="10.000", trade_date=date(2026, 7, 1),
    )


class TestAnnualReportService:
    def test_no_trades(self):
        out = asyncio.run(get_annual_report(2026))
        assert out["year"] == 2026
        assert out["closed_count"] == 0
        assert out["win_rate"] == 0.0
        assert out["top5_profit"] == []
        assert out["top5_loss"] == []

    def test_basic_year(self):
        asyncio.run(_seed_year_2026())
        out = asyncio.run(get_annual_report(2026))
        # 600519 卖 500@15 - 成本 10 → realized = 2500(仅部分卖出,未构成完整平仓周期)
        # 000001 卖 200@10 - 成本 20 → realized = -2000(完整清仓 = 一个平仓周期,亏损)
        # IR-5:win_rate 按平仓周期聚合 → 1 个周期且为亏,胜率 0.0(旧口径按笔数=0.5)
        assert out["closed_count"] == 2
        assert Decimal(out["net_pnl"]) == Decimal("500")  # 2500 - 2000
        assert Decimal(out["realized_profit"]) == Decimal("2500")
        assert Decimal(out["realized_loss"]) == Decimal("2000")
        assert out["closed_cycles"] == 1
        assert out["win_rate"] == 0.0
        # Top5
        assert out["top5_profit"][0]["stock_code"] == "600519.SH"
        assert Decimal(out["top5_profit"][0]["realized_pnl"]) == Decimal("2500")
        assert out["top5_loss"][0]["stock_code"] == "000001.SZ"

    def test_cycle_win_rate(self):
        """IR-5:完整建仓→清仓周期聚合胜率(中途减仓不算一个周期)"""
        # 周期1:600519 买1000@10 → 卖500@15(减仓) → 卖500@16(清仓)= 盈利周期
        # 周期2:000001 买200@20 → 卖200@10(清仓)= 亏损周期
        # 买入都发生在 2025 年末 → 周期闭合在 2026,2026 应计 2 个周期
        seed = [
            ("600519.SH", "A", "buy", 1000, "10.000", date(2025, 12, 20)),
            ("600519.SH", "A", "sell", 500, "15.000", date(2026, 1, 5)),
            ("600519.SH", "A", "sell", 500, "16.000", date(2026, 1, 8)),
            ("000001.SZ", "B", "buy", 200, "20.000", date(2025, 12, 25)),
            ("000001.SZ", "B", "sell", 200, "10.000", date(2026, 2, 1)),
        ]
        for code, name, action, shares, price, d in seed:
            asyncio.run(transaction_repo.create(
                stock_code=code, stock_name=name, action=action,
                shares=shares, price=price, trade_date=d,
            ))
        out = asyncio.run(get_annual_report(2026))
        assert out["closed_count"] == 3      # 3 笔卖出
        assert out["closed_cycles"] == 2     # 2 个完整平仓周期
        assert out["win_rate"] == 0.5        # 1 赚 1 亏

    def test_year_filter_excludes_other_years(self):
        """2025 年买入 → 2026 年卖出:2025 不计,2026 计 realized"""
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="buy",
            shares=100, price="10.000", trade_date=date(2025, 1, 1),
        ))
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="sell",
            shares=100, price="20.000", trade_date=date(2026, 6, 1),
        ))
        out = asyncio.run(get_annual_report(2025))
        assert out["closed_count"] == 0  # 2025 只买不卖
        out = asyncio.run(get_annual_report(2026))
        assert out["closed_count"] == 1
        assert Decimal(out["net_pnl"]) == Decimal("1000")  # (20-10)*100

    def test_all_win(self):
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="buy",
            shares=100, price="10.000", trade_date=date(2026, 3, 1),
        ))
        asyncio.run(transaction_repo.create(
            stock_code="000001.SZ", stock_name="B", action="buy",
            shares=100, price="20.000", trade_date=date(2026, 4, 1),
        ))
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="sell",
            shares=100, price="15.000", trade_date=date(2026, 5, 1),
        ))
        asyncio.run(transaction_repo.create(
            stock_code="000001.SZ", stock_name="B", action="sell",
            shares=100, price="25.000", trade_date=date(2026, 6, 1),
        ))
        out = asyncio.run(get_annual_report(2026))
        assert out["win_rate"] == 1.0
        assert out["top5_loss"] == []

    def test_all_loss(self):
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="buy",
            shares=100, price="10.000", trade_date=date(2026, 3, 1),
        ))
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="sell",
            shares=100, price="5.000", trade_date=date(2026, 5, 1),
        ))
        out = asyncio.run(get_annual_report(2026))
        assert out["win_rate"] == 0.0
        assert out["top5_profit"] == []

    def test_top5_limit(self):
        """超过 5 笔时只取前 5"""
        for i in range(7):
            asyncio.run(transaction_repo.create(
                stock_code=f"60000{i}.SH", stock_name=f"S{i}", action="buy",
                shares=100, price="10.000", trade_date=date(2026, 3, 1),
            ))
            asyncio.run(transaction_repo.create(
                stock_code=f"60000{i}.SH", stock_name=f"S{i}", action="sell",
                shares=100, price=f"{11 + i}.000", trade_date=date(2026, 5, 1),
            ))
        out = asyncio.run(get_annual_report(2026))
        assert out["closed_count"] == 7
        assert len(out["top5_profit"]) == 5
        assert len(out["top5_loss"]) == 0  # 全赚


class TestAnnualReportAPI:
    def test_get_report(self, client):
        asyncio.run(_seed_year_2026())
        r = client.get("/api/annual-report/2026")
        assert r.status_code == 200
        body = r.json()
        assert body["year"] == 2026
        assert body["closed_count"] == 2

    def test_invalid_year(self, client):
        r = client.get("/api/annual-report/1999")
        assert r.status_code == 400
        r = client.get("/api/annual-report/2200")
        assert r.status_code == 400


class TestFeesDualMetric:
    """GB-001 IR-4:费用双口径(默认关闭 → gross=net)"""

    @pytest.fixture()
    def enable_fees(self, client):
        """开启费用参数(佣金万2.5/最低5元/印花税0.05%/过户费0.001%)"""
        from app.repositories.cost_settings_repo import cost_settings_repo

        asyncio.run(cost_settings_repo.save(
            enabled=True,
            commission_rate="0.00025",
            min_commission="5.00",
            stamp_tax_rate="0.0005",
            transfer_fee_rate="0.00001",
        ))
        yield
        asyncio.run(cost_settings_repo.save(
            enabled=False,
            commission_rate="0.00025",
            min_commission="5.00",
            stamp_tax_rate="0.0005",
            transfer_fee_rate="0.00001",
        ))

    def test_fees_disabled_default(self, client):
        """默认关闭:net == gross,不改变旧数字"""
        asyncio.run(_seed_year_2026())
        out = asyncio.run(get_annual_report(2026))
        assert out["fees_enabled"] is False
        assert out["net_pnl"] == out["net_pnl_gross"]
        assert out["total_fee"] == "0.00"

    def test_fees_enabled_deducts_fee(self, client, enable_fees):
        """开启后 net < gross(卖出付印花税+佣金+过户费)"""
        asyncio.run(_seed_year_2026())
        out = asyncio.run(get_annual_report(2026))
        assert out["fees_enabled"] is True
        assert Decimal(out["net_pnl"]) < Decimal(out["net_pnl_gross"])
        assert Decimal(out["total_fee"]) > 0
        # 卖出费用:佣金≥5 + 印花税 + 过户费(2 笔卖出;买入费用入成本不在此汇总)
        fee = Decimal(out["total_fee"])
        assert fee >= Decimal("5.00") * 2  # 2 笔卖出最低佣金

    def test_calc_fee_direction(self):
        """费用方向:买入计入成本、卖出扣已实现(IR-4 修复要点)"""
        from app.core.cost_engine import TradeFees, calculate_after_transaction
        from decimal import Decimal

        fees = TradeFees(
            enabled=True,
            commission_rate=Decimal("0.00025"),
            min_commission=Decimal("5.00"),
            stamp_tax_rate=Decimal("0.0005"),
            transfer_fee_rate=Decimal("0.00001"),
        )
        # 买入 1000@10:总成本 = 10000 + 佣金5 + 过户0.10 = 10005.10
        r_buy = calculate_after_transaction(
            shares_before=0, cost_before=Decimal("0"),
            action="buy", tx_shares=1000, tx_price=Decimal("10.000"),
            fees=fees,
        )
        assert r_buy["total_cost_after"] == Decimal("10005.10")
        assert r_buy["fee_paid"] == Decimal("5.10")
        # 卖出 1000@15:毛盈亏 (15-10.0051)*1000,净 = 毛 - (佣金5 + 印花税7.50 + 过户0.15)
        r_sell = calculate_after_transaction(
            shares_before=1000, cost_before=r_buy["cost_after"],
            action="sell", tx_shares=1000, tx_price=Decimal("15.000"),
            fees=fees,
        )
        gross = r_sell["realized_pnl_gross"]
        net = r_sell["realized_pnl_net"]
        fee = r_sell["fee_paid"]
        assert fee == Decimal("12.65")  # 5 + 7.50 + 0.15
        assert net == gross - fee
        assert net < gross

    def test_t_contribution_and_dietz(self, client):
        """IR-5:做 T 卖出计入 T 净贡献;时间加权收益率有输出"""
        # 600519:3/1 买1000@10,3/2 卖500@12(做T,1日内反向)
        # 000001:3/1 买200@20,3/5 卖200@25(非T,清仓周期)
        for code, name, action, shares, price, d in [
            ("600519.SH", "A", "buy", 1000, "10.000", date(2026, 3, 1)),
            ("600519.SH", "A", "sell", 500, "12.000", date(2026, 3, 2)),
            ("000001.SZ", "B", "buy", 200, "20.000", date(2026, 3, 1)),
            ("000001.SZ", "B", "sell", 200, "25.000", date(2026, 3, 5)),
        ]:
            asyncio.run(transaction_repo.create(
                stock_code=code, stock_name=name, action=action,
                shares=shares, price=price, trade_date=d,
            ))
        out = asyncio.run(get_annual_report(2026))
        # T 净贡献 = 做T卖出的净已实现 = (12-10)*500 = 1000(费率关闭)
        assert Decimal(out["t_net_contribution"]) == Decimal("1000.00")
        # 趋势 = 总 - T = (5*200 + 2*500) - 1000 = 1000
        assert Decimal(out["trend_net_pnl"]) == Decimal("1000.00")
        # 平仓周期:600519 未清仓不算完整周期;000001 清仓 1 周期(盈利)
        assert out["closed_cycles"] == 1
        assert out["dietz_return"] is not None


from decimal import Decimal  # noqa: E402  (放在文件末尾,被测试用例引用)