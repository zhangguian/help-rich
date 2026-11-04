"""按券商持仓快照修正导入基准 + 全量重放成本链(一次性脚本,可重复执行)

背景(v0.11 摊薄成本口径):
    券商持仓页的「成本价」= 摊薄成本 = 累计净投入 ÷ 持股数。
    系统改成摊薄口径后,基准(base_*)必须是「券商摊薄总额 + 券商股数」,
    否则摊薄成本与券商对不上。

    基准怎么推:
        设基准 (S0, D0, R0),活链(id > base_tx_id)的净股数 ΔS、净现金流 ΔD:
            D(净投入)只随现金流变化 → D_final = D0 + ΔD
            S_final = S0 + ΔS
        要 D_final = 券商摊薄总额、S_final = 券商股数,于是:
            S0 = 券商股数 − ΔS
            D0 = 券商摊薄总额 − ΔD
        基准的已实现 R0 **保持原值**(券商给的累计已实现),不参与摊薄总额的推算。

用法(在 backend/ 目录下):
    python -m scripts.fix_base_to_broker --dry-run     # 只算不写
    python -m scripts.fix_base_to_broker                # 落库 + 重放全量链

幂等:重复执行安全(基准写成确定值,重放是纯函数)。
"""
import argparse
import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.db import async_session
from app.models.orm import Position as PositionRow
from app.models.orm import Transaction
from app.modules.portfolio.service import recalc_position

# 券商持仓快照(2026-11-04 用户截图):代码 → (股数, 摊薄成本价)
#
# 深A股(5 只)+ ETF/LOF(6 只)分两张表截的,股数是**实际数量**(含当日买入、剔除当日卖出在途)。
BROKER_SNAPSHOT: dict[str, tuple[int, Decimal]] = {
    # ---- 深A股 ----
    "000066.SZ": (200, Decimal("18.572")),   # 中国长城
    "000657.SZ": (300, Decimal("53.464")),   # 中钨高新
    "000807.SZ": (100, Decimal("8.090")),    # 云铝股份
    "001896.SZ": (600, Decimal("15.553")),   # 豫能控股
    "002185.SZ": (1100, Decimal("16.840")),  # 华天科技
    # ---- ETF / LOF ----
    "159599.SZ": (200, Decimal("4.588")),    # 芯片指数
    "159732.SZ": (1800, Decimal("2.006")),   # 消费电子
    "501099.SH": (1700, Decimal("4.914")),   # 新兴平安
    "561980.SH": (500, Decimal("0.822")),    # 芯片设备
    "562820.SH": (300, Decimal("1.972")),    # 集成电路
    "588160.SH": (2100, Decimal("1.367")),   # 科创新材
}


async def _load(session, code: str) -> tuple[PositionRow, list[Transaction]]:
    row = (
        await session.execute(
            select(PositionRow).where(
                PositionRow.account_id == 1,
                PositionRow.stock_code == code,
            )
        )
    ).scalar_one()
    txs = list(
        (
            await session.execute(
                select(Transaction)
                .where(
                    Transaction.account_id == 1,
                    Transaction.stock_code == code,
                )
                .order_by(Transaction.id)
            )
        )
        .scalars()
        .all()
    )
    return row, txs


def _chain_delta(txs: list[Transaction], base_tx_id: int) -> tuple[int, Decimal]:
    """活链的净股数 ΔS 与净现金流 ΔD(买入加、卖出减)"""
    d_shares = 0
    d_cash = Decimal(0)
    for t in txs:
        if t.id <= base_tx_id:
            continue
        amount = Decimal(t.price) * t.shares
        if t.action == "buy":
            d_shares += t.shares
            d_cash += amount
        else:
            d_shares -= t.shares
            d_cash -= amount
    return d_shares, d_cash


async def _run(dry_run: bool) -> None:
    async with async_session() as session:
        codes = list(BROKER_SNAPSHOT.keys())
        rows = (
            await session.execute(
                select(PositionRow).where(PositionRow.account_id == 1)
            )
        ).scalars().all()
        all_codes = [r.stock_code for r in rows]

        plan: list[dict] = []
        for code in codes:
            row, txs = await _load(session, code)
            d_shares, d_cash = _chain_delta(txs, row.base_tx_id)
            b_shares, b_cost = BROKER_SNAPSHOT[code]
            broker_total = b_cost * b_shares
            target_s0 = b_shares - d_shares
            target_d0 = broker_total - d_cash
            plan.append(
                {
                    "code": code,
                    "name": row.stock_name,
                    "old_s0": row.base_shares,
                    "old_d0": Decimal(row.base_total_cost),
                    "r0": Decimal(row.base_realized_pnl),
                    "new_s0": target_s0,
                    "new_d0": target_d0,
                    "broker_shares": b_shares,
                    "broker_cost": b_cost,
                    "d_shares": d_shares,
                    "d_cash": d_cash,
                }
            )

        print("=" * 78)
        print("基准修正计划(摊薄口径)")
        print("=" * 78)
        for p in plan:
            print(f"\n{p['code']} {p['name']}")
            print(
                f"  基准股数  {p['old_s0']} → {p['new_s0']}"
                f"   (券商 {p['broker_shares']}, 活链 ΔS={p['d_shares']})"
            )
            print(
                f"  基准总额  {p['old_d0']} → {p['new_d0']}"
                f"   (券商总额 {p['broker_cost'] * p['broker_shares']}, 活链 ΔD={p['d_cash']})"
            )
            print(f"  基准已实现 {p['r0']}(保持不变)")

        if dry_run:
            print("\n--dry-run:未写库")
            return

        for p in plan:
            row, _txs = await _load(session, p["code"])
            row.base_shares = int(p["new_s0"])
            row.base_total_cost = str(p["new_d0"].quantize(Decimal("0.01")))
        await session.commit()

    # 重放全量链(基准改了 + 成本口径改了 → 所有持仓行与流水快照都要重算)
    for code in all_codes:
        await recalc_position(code)

    # 复核
    async with async_session() as session:
        print("\n" + "=" * 78)
        print("重放后 vs 券商")
        print("=" * 78)
        for code in all_codes:
            row = (
                await session.execute(
                    select(PositionRow).where(
                        PositionRow.account_id == 1,
                        PositionRow.stock_code == code,
                    )
                )
            ).scalar_one()
            if row.shares <= 0:
                continue
            cost = Decimal(row.total_cost) / row.shares
            mark = ""
            if code in BROKER_SNAPSHOT:
                b_shares, b_cost = BROKER_SNAPSHOT[code]
                if row.shares == b_shares and cost.quantize(Decimal("0.001")) == b_cost:
                    mark = "  [OK] broker matched"
                else:
                    mark = f"  [MISMATCH] broker {b_shares}@{b_cost}"
            print(
                f"  {code} {row.stock_name or ''}: {row.shares} 股 @ "
                f"{cost.quantize(Decimal('0.001'))}  已实现 {row.realized_pnl}{mark}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="按券商快照修正导入基准 + 重放成本链")
    parser.add_argument("--dry-run", action="store_true", help="只算不写")
    args = parser.parse_args()
    asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    main()
