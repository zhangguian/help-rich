"""补T待接回 / 待卖出清单 API

口径(单一,不搞多套推断):
  做T挂单有两种方向(见 `t_pairing.py`),清单也分两组:

  | 组 | 方向 | 含义 | 基准线 | 三档方向 |
  |----|------|------|--------|----------|
  | 待接回 | 反T(先卖后买) | 卖出了还没买回来 | 不亏本接回线 = 净卖出加权均价 | 往下(越等越便宜) |
  | 待卖出 | 正T(先买后卖) | 买进了还没卖出去 | 买入加权均价 | 往上(越等越贵) |

  为什么用「全链未闭合」而不是「只看最近一个交易日」:
  卖出腿和接回腿天然可能跨天(今天卖、明天接回是标准做T节奏)。
  只看当天会把「卖 200 只接回 100」剩下的 100 股直接丢掉,用户根本看不到还差多少。
  全链 FIFO 走完后**没被闭合的开腿**就是还挂着的做T单 —— 跨几天都留着,直到接回/卖出为止。
  两组共用同一份配对结果(与做T历史同源),不会出现两处口径打架。

  建议价分三档(见 `t_pricing.py`):一档 1%、二档 2%、三档 3%。
  每档都给「这一档的价格」+「按这一档成交之后的摊薄成本线」——
  一眼看出做到哪一档最划算;两档之间差的是「多赚一点」与「多等一会儿」的取舍。

  每条挂单还带**当初开腿的成交价**(`open_prices`):
  反T = 当初卖出的价,正T = 当初买入的价。
  ⚠️ 与基准线(`price`)不是一回事 —— 基准线是**算出来的**(多笔开腿时 = 加权均价),
  `open_prices` 是**真成交价**:同一只票做了两次T(两笔开腿)就会有两个价,逐笔列出来。

  到价提醒自动管理(见 `t_alerts.py`):
  每条挂单自动保证有一个到价提醒 —— 反T `price <= 一档价`、正T `price >= 一档价`。
  挂单接回/卖出后自动从清单消失,对应的自动提醒同时停用。

  GET /api/t-reminders/pending → 待接回 + 待卖出清单(+ 每条的到价提醒状态)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.core.logging import logger
from app.db import async_session
from app.models.orm import Transaction
from app.modules.portfolio.t_pairing import DIRECTION_FORWARD, DIRECTION_REVERSE
from app.modules.portfolio.t_pricing import TTier, build_tiers

if TYPE_CHECKING:
    from app.modules.portfolio.t_alerts import AutoAlertSyncStats

router = APIRouter(prefix="/t-reminders", tags=["t-reminders"])


def _to_float(value: object) -> float | None:
    """转 float;非有限值(NaN / ±inf)与转换失败一律当**无效**(None)。

    与 `alert/scheduler.py` / `services/intraday_advice._f` 同一口径。
    ⚠️ NaN / ±inf **不是合法 JSON** —— 直接返回会让整个接口 500。
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


class TReminderItem(BaseModel):
    """一条做T挂单(一只票 = 一条)"""

    stock_code: str
    stock_name: str | None = None
    # 方向:reverse = 反T(先卖后买,待接回) / forward = 正T(先买后卖,待卖出)
    direction: str
    # 待接回 / 待卖出的股数
    shares: int
    # 反T:不亏本接回线(净卖出的加权均价)
    # 正T:买入加权均价
    price: float
    # 一档建议价 —— 反T=建议接回价(线再低 1%),正T=建议卖出价(均价再高 1%)
    suggested_price: float | None = None
    # 三档建议价 + 每档成交后的成本前→后
    tiers: list[TTier] = []
    # 开腿日期(挂单从哪天起的 —— 同一标的同一方向多笔卖出取最早那个)
    open_date: str
    # **当初那笔开腿流水的成交价**(反T = 当初卖出价,正T = 当初买入价)
    #
    # ⚠️ 与 `price`(不亏本线 / 买入均价)不是一回事:
    #    `price` 是**算出来的阈值**(多笔开腿时 = 加权均价),
    #    这里是**真成交价** —— 同一只票做了两次T(两笔开腿)就会有两个价。
    # 按开腿顺序(日期 → 流水 id)排;空 = 理论上不该发生(有挂单必有开腿)。
    open_prices: list[float] = []
    # 组成这条挂单的**开腿流水 id**(同一标的同一方向可能有多笔 → 多 id)
    # 前端「编辑」用它定位到具体那一笔;空 = 理论上不该发生(有挂单必有开腿)
    open_tx_ids: list[int] = []
    # 当前持仓股数(0 = 已清空)
    position_shares: int | None = None
    # 现价(行情不可用时为 null)
    current_price: float | None = None
    # 到价提醒 id(没有则 null)
    alert_id: int | None = None
    # 该提醒的触发价
    alert_price: float | None = None
    # 该提醒落在第几档
    alert_tier: int | None = None
    # 该提醒是不是系统自动建的(自动建的挂单消失时会自动停用)
    alert_auto: bool = False
    # 用户自己建的到价提醒 id(同标的 + 同方向);没有则 null
    manual_alert_id: int | None = None
    manual_alert_price: float | None = None
    # ---- 预警(到价之前先给一次「准备」信号)----
    # 预警提醒 id;没有则 null
    pre_alert_id: int | None = None
    # 预警线价格(= 生效到价线朝基准线方向再退 1%)
    pre_alert_price: float | None = None
    # 这条预警是不是已经响过了(一次性提醒命中后自动停用)
    pre_alert_fired: bool = False
    # 距到价线还差百分之几(正数);现价未知 → null
    pre_alert_distance_pct: float | None = None
    # 现价是否已经越过到价线
    pre_alert_reached: bool = False
    # 现价是否已经进入预警区(该准备了)
    pre_alert_in_zone: bool = False
    # 当前成本线(持仓摊薄成本价 = 券商持仓页的「成本价」)
    cost_before: float | None = None
    # 按一档建议价成交之后的成本线(摊薄成本)
    cost_after: float | None = None


class TReminderListOut(BaseModel):
    # 待接回(反T:先卖后买)
    items: list[TReminderItem]
    count: int
    # 待卖出(正T:先买后卖)
    forward_items: list[TReminderItem]
    forward_count: int
    # 两组合计
    total_count: int
    # 清单口径的基准日(取各标的最近一次动作日,此字段取最大值)
    as_of: str | None = None
    # 本次同步自动新建的到价提醒条数
    auto_alerts_created: int = 0
    # 本次同步自动停用的到价提醒条数(挂单已消失)
    auto_alerts_disabled: int = 0
    # 本次同步把自动提醒的价格拉回一档的条数(基准线变了 / 被改成了档位外的价)
    auto_alerts_realigned: int = 0
    # 本次同步新建的预警提醒条数
    pre_alerts_created: int = 0
    # 本次同步把已响过的预警提醒**重新武装**的条数(价格离开预警区了)
    pre_alerts_rearmed: int = 0
    # 本次同步停用的预警提醒条数(挂单已消失)
    pre_alerts_disabled: int = 0
    # 本次同步把预警线就地改掉的条数(到价线变了,预警线跟着走)
    pre_alerts_realigned: int = 0
    # 本次同步停用的「被认领过的手工提醒」条数(挂单已消失)
    claimed_alerts_disabled: int = 0


def _chain_order(t: Transaction) -> tuple:
    """链序全序键(与 portfolio.service.chain_sort_key 同一口径)。"""
    from datetime import time as time_mod

    return (t.trade_date, t.trade_time or time_mod.min, t.id)


def _name_of(txs: list[Transaction] | None) -> str | None:
    """取该标的最近一次带名称的流水上的股票名。

    ⚠️ 名称可能**三处都缺**:流水的 `stock_name` 是录入时填的,
    补T清单里那几笔(如 501099.SH / 562820.SH / 159599.SZ)是**从持仓侧录的**,
    流水没带名称 → 这里必须回退到**持仓行**的名称(持仓行是导入基准时写好的)。
    持仓行也没有 → 返回 None(不编名字,前端显示「—」)。
    """
    if not txs:
        return None
    for t in reversed(txs):
        if t.stock_name:
            return t.stock_name
    return None


def _name_for(
    txs: list[Transaction] | None,
    positions: dict[str, object],
    code: str,
) -> str | None:
    """挂单的显示名:流水名 → 持仓行名 → None。"""
    return _name_of(txs) or getattr(positions.get(code), "stock_name", None)


def _open_prices(slot: dict) -> list[float]:
    """当初开腿的成交价(反T = 卖出价,正T = 买入价)。

    按开腿顺序(日期 → 流水 id)排;量化到 3 位小数 —— 与挂单其它价格同一口径,
    避免浮点噪音(2.3219999)。
    """
    ordered = sorted(slot.get("open_prices", []), key=lambda x: (x[0], x[1]))
    return [float(p.quantize(Decimal("0.001"))) for _, _, p in ordered]


async def build_reminder_items(
    codes: set[str] | None = None,
) -> list[TReminderItem]:
    """构建做T挂单清单(到价提醒同步**不在这里**做,由调用方决定)。

    `codes`:
      - None  = 全量(补T清单页的行为);
      - 给定集合 = 只构建这些标的的挂单(录入流水后只关心这一只)。

    为什么抽出来:
      「打开补T清单」和「刚录完一笔流水」需要的是**同一份**挂单口径
      (全链 FIFO + 三档建议价 + 现价)。两处各写一遍迟早口径打架。

    行情取不到时 current_price 为 null —— 不编数字。
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID
    from app.modules.portfolio.service import get_all_positions
    from app.modules.portfolio.t_pairing import STATUS_PENDING, pair_t_legs

    stmt = select(Transaction).where(Transaction.account_id == DEFAULT_ACCOUNT_ID)
    if codes is not None:
        stmt = stmt.where(Transaction.stock_code.in_(sorted(codes)))

    async with async_session() as session:
        rows = list((await session.execute(stmt)).scalars().all())

    # 按标的分组 → 全链 FIFO 配对 → 未闭合的开腿 = 还挂着的做T单
    by_code: dict[str, list[Transaction]] = {}
    for t in rows:
        by_code.setdefault(t.stock_code, []).append(t)

    reverse_items: list[TReminderItem] = []
    forward_items: list[TReminderItem] = []
    # 同一标的 + 同一方向的多笔挂单合并成一条(股数累加,金额累加 → 加权均价)
    reverse_agg: dict[str, dict] = {}
    forward_agg: dict[str, dict] = {}

    for code, txs in by_code.items():
        txs.sort(key=_chain_order)
        pairs = pair_t_legs(
            [
                (t.id, t.action, int(t.shares), Decimal(t.price), t.trade_date)
                for t in txs
            ],
            lambda _tx_id: (None, None),
        )

        for pair in pairs:
            if pair.status != STATUS_PENDING:
                continue
            is_reverse = pair.direction == DIRECTION_REVERSE
            agg = reverse_agg if is_reverse else forward_agg
            slot = agg.setdefault(
                code,
                {
                    "shares": 0,
                    "amount": Decimal(0),
                    "open_date": None,
                    "tx_ids": [],
                    "open_prices": [],
                },
            )
            slot["shares"] += pair.shares
            slot["amount"] += pair.open_amount
            if slot["open_date"] is None or pair.open_date < slot["open_date"]:
                slot["open_date"] = pair.open_date
            # 组成这条挂单的流水 id(前端「编辑」时定位到具体那一笔)
            slot["tx_ids"].append(pair.open_tx_id)
            # 当初开腿的成交价(反T=卖出价,正T=买入价)—— 逐笔记,不是加权均价
            slot["open_prices"].append((pair.open_date, pair.open_tx_id, pair.open_price))

    # 持仓行:名称回退的来源(流水没带名字 → 用持仓行的名字)
    positions = {p.stock_code: p for p in await get_all_positions()}

    for code, slot in reverse_agg.items():
        avg = (slot["amount"] / slot["shares"]).quantize(Decimal("0.001"))
        reverse_items.append(
            TReminderItem(
                stock_code=code,
                stock_name=_name_for(by_code.get(code), positions, code),
                direction=DIRECTION_REVERSE,
                shares=slot["shares"],
                price=float(avg),
                open_date=slot["open_date"].isoformat(),
                open_tx_ids=sorted(slot["tx_ids"]),
                open_prices=_open_prices(slot),
            )
        )
    for code, slot in forward_agg.items():
        avg = (slot["amount"] / slot["shares"]).quantize(Decimal("0.001"))
        forward_items.append(
            TReminderItem(
                stock_code=code,
                stock_name=_name_for(by_code.get(code), positions, code),
                direction=DIRECTION_FORWARD,
                shares=slot["shares"],
                price=float(avg),
                open_date=slot["open_date"].isoformat(),
                open_tx_ids=sorted(slot["tx_ids"]),
                open_prices=_open_prices(slot),
            )
        )

    # 持仓股数 + 三档建议价(每档带成本前→后)
    #
    # 摊薄口径(v0.11):摊薄总额 = 净投入,买入即增加、卖出按成交价回收。
    # 没有持仓行(理论上不会发生:有挂单必有持仓)→ 成本字段留 null,不编数字。
    # (positions 已在上面加载 —— 名称回退要用它)
    all_items = reverse_items + forward_items
    for it in all_items:
        pos = positions.get(it.stock_code)
        if pos is None or pos.shares <= 0:
            it.position_shares = int(pos.shares) if pos is not None else None
            it.tiers = build_tiers(
                Decimal(str(it.price)),
                it.direction,
                shares=it.shares,
            )
            it.suggested_price = it.tiers[0].price
            it.cost_before = None
            it.cost_after = None
            continue
        it.position_shares = int(pos.shares)
        it.tiers = build_tiers(
            Decimal(str(it.price)),
            it.direction,
            shares=it.shares,
            total_cost=pos.total_cost,
            position_shares=int(pos.shares),
        )
        it.suggested_price = it.tiers[0].price
        it.cost_before = it.tiers[0].cost_before
        it.cost_after = it.tiers[0].cost_after

    # 现价(行情不可用就留 null)
    if all_items:
        try:
            from app.services.quote_service import get_quote_service

            quotes = {
                q.code: q
                for q in await get_quote_service().get_quotes(
                    [it.stock_code for it in all_items]
                )
            }
            for it in all_items:
                q = quotes.get(it.stock_code)
                if q is None:
                    continue
                # ⚠️ 无效行情必须当"没有" —— 不能把 0 / NaN 塞进 current_price:
                # ① `price <= 0` 是停牌/开盘瞬间的占位值,当现价会让清单显示 0.000;
                # ② NaN / ±inf 不是合法 JSON,序列化会直接把整个接口打成 500。
                # 口径与 `alert/scheduler.py` 的行情过滤一致(行情取不到 = null,不编数据)。
                price = _to_float(q.current_price)
                if price is None or price <= 0:
                    continue
                it.current_price = price
        except Exception as e:  # noqa: BLE001 — 行情失败不阻断清单
            logger.warning(f"[t-reminders] 行情拉取失败,现价留空: {e}")

    return all_items


async def sync_t_alerts_for_stock(stock_code: str) -> AutoAlertSyncStats | None:
    """录完流水后**立刻**对齐该标的的做T提醒(建第二腿提醒 / 停用已闭合的提醒)。

    为什么不能只靠打开补T清单页:
      做T的第二步(接回 / 卖出)提醒,是在**第一腿录入之后**才该出现的。
      同步只挂在 `GET /api/t-reminders/pending` 上的话,用户录完第一腿就关页面,
      第二腿的到价提醒永远不会被建出来 —— 价格到了也不会响。
      与「页面关着也要能收到」同源:状态流转不能只挂在前端副作用上。

    `scope_codes={stock_code}`:只同步这一只,不碰别的标的的提醒。

    返回值:同步统计(供调用方记日志);失败返回 None,绝不让录入失败。
    """
    from app.modules.portfolio.t_alerts import sync_auto_alerts

    try:
        items = await build_reminder_items({stock_code})
        return await sync_auto_alerts(items, scope_codes={stock_code})
    except Exception as e:  # noqa: BLE001 — 提醒同步失败不该让录入失败
        logger.warning(f"[t-reminders] 录入后同步做T提醒失败 {stock_code}: {e}")
        return None


@router.get("/pending", response_model=TReminderListOut)
async def list_pending() -> TReminderListOut:
    """待接回(反T)+ 待卖出(正T)清单。

    行情取不到时 current_price 为 null —— 不编数字。
    """
    all_items = await build_reminder_items()

    reverse_items = [it for it in all_items if it.direction == DIRECTION_REVERSE]
    forward_items = [it for it in all_items if it.direction == DIRECTION_FORWARD]

    # 清单基准日 = 各挂单开腿日的最大值
    as_of: date | None = None
    for it in all_items:
        d = date.fromisoformat(it.open_date)
        if as_of is None or d > as_of:
            as_of = d

    # 到价提醒:自动对齐(缺就建,挂单消失就停用)
    from app.modules.portfolio.t_alerts import sync_auto_alerts

    try:
        sync_stats = await sync_auto_alerts(all_items)
    except Exception as e:  # noqa: BLE001 — 提醒同步失败不该拖垮清单
        logger.warning(f"[t-alerts] 自动同步到价提醒失败: {e}")
        sync_stats = None

    reverse_items.sort(key=lambda x: (-x.shares * x.price, x.stock_code))
    forward_items.sort(key=lambda x: (-x.shares * x.price, x.stock_code))
    return TReminderListOut(
        items=reverse_items,
        count=len(reverse_items),
        forward_items=forward_items,
        forward_count=len(forward_items),
        total_count=len(reverse_items) + len(forward_items),
        as_of=as_of.isoformat() if as_of else None,
        auto_alerts_created=sync_stats.created if sync_stats else 0,
        auto_alerts_disabled=sync_stats.disabled if sync_stats else 0,
        auto_alerts_realigned=sync_stats.realigned if sync_stats else 0,
        pre_alerts_created=sync_stats.pre_created if sync_stats else 0,
        pre_alerts_rearmed=sync_stats.pre_rearmed if sync_stats else 0,
        pre_alerts_disabled=sync_stats.pre_disabled if sync_stats else 0,
        pre_alerts_realigned=sync_stats.pre_realigned if sync_stats else 0,
        claimed_alerts_disabled=sync_stats.claimed_disabled if sync_stats else 0,
    )
