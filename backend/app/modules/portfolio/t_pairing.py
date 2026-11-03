"""做T配对内核(正T / 反T 双向 FIFO)

口径(单一,不搞多套推断):
  做T有两种方向,腿的先后顺序不同:

  | 方向 | 中文 | 开腿 | 收腿 | 目的 |
  |------|------|------|------|------|
  | 反T  | reverse | 卖出(先卖) | 买回(后买) | 高抛低吸,锁定差价 |
  | 正T  | forward | 买入(先买) | 卖出(后卖) | 低吸高抛,波段做T |

  配对规则:
  - 按链全序(交易日, 时间点, id)走一遍流水,FIFO:后一笔优先闭合**最早**的开腿。
  - 遇到**买入**:先闭合 `pending_sell`(反T开腿,先卖后买),剩余部分成为 `pending_buy`(正T开腿)。
  - 遇到**卖出**:先闭合 `pending_buy`(正T开腿,先买后卖),剩余部分成为 `pending_sell`(反T开腿)。
  - 链尾还没被闭合的开腿 = **挂单中**:
      反T开腿未闭合 → 待接回
      正T开腿未闭合 → 待卖出

  为什么买入先闭合反T、卖出先闭合正T:
    同一标的同一段时间里,「先卖出的」和「先买入的」必然是两次独立动作。
    先遇到的那条腿才是上一轮做T留下的挂单,后遇到的那条腿是新动作。
    所以后一笔永远去闭合先一笔 —— 反T的挂单等买入来结,正T的挂单等卖出到齐。

  每个口径的盈亏:
  - `t_pnl`        做T差价盈亏 = (卖出价 − 买入价) × T股数
                    两个方向都是「低买高卖赚差价」,正数 = 这波做T赚钱了。
                    没闭合(还挂着)时价差还不存在 → null(不编数字)。
  - `realized_pnl` 卖出确认的已实现盈亏 = (卖出价 − 卖出那一刻的摊薄成本) × 股数
                    反T在**开腿**(卖出)时就确认,正T在**收腿**(卖出)时才确认。
  - `cost_before`  开腿那一刻的持仓摊薄成本(券商口径)
  - `cost_after`   收腿之后的持仓摊薄成本

  成本来自成本链(基准 + 活链重放,摊薄口径)。基准吸收掉的早期流水没有逐笔成本
  → cost_before / cost_after / realized_pnl 为 null(不编数字)。

  纯函数,不碰数据库 —— 做T历史与补T清单共用这一份判定,避免两处口径打架。

  **时间窗口**(关键):配对只在**相隔不超过 T_PAIR_WINDOW_DAYS 天**时才成立。
  没有窗口的话,「10 月 13 日买的票,11 月 2 日割掉」会被当成一次正T(先买后卖),
  而「今天卖、明天接回」也会因为更早的一笔买入而被配错腿。
  做T是**短周期**动作 —— 隔了半个月的买卖不是做T,是加仓或割肉。
  超窗口的腿会被**冻结**(不再参与配对,单独作为加仓/减仓挂着),
  窗口以链上最后一个流水的日期为基准(确定性,不随「今天」漂移)。
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

# 做T方向
DIRECTION_REVERSE = "reverse"  # 反T:先卖出、后买回(高抛低吸)
DIRECTION_FORWARD = "forward"  # 正T:先买入、后卖出(低吸高抛)

# 做T状态
STATUS_CLOSED = "closed"  # 两腿都齐了
STATUS_PENDING = "pending"  # 还挂着一条腿,等另一条来闭合

# 做T配对的时间窗口(天)
#
# 为什么是 3 天:做T的标准节奏是「当天卖、次日接回」,周五卖、下周一接回也正好 3 天。
# 再长的间隔就不是做T了 —— 是加仓后调仓、或者套住后割肉。
# 改这个常量就能放宽/收紧,口径集中在一处。
T_PAIR_WINDOW_DAYS = 3


@dataclass
class TLeg:
    """一条做T开腿(已发生、还没被闭合的那一段)

    left/amount 随配对递减 —— 剩余股数与剩余金额(用于算加权均价)。
    """

    tx_id: int
    trade_date: date
    price: Decimal
    left: int
    amount: Decimal
    # 开腿那一刻的摊薄成本(券商口径);没有成本基准时为 None
    cost_before: Decimal | None = None
    # 已被时间窗口冻结 —— 与收腿相隔太久,不是做T,不再参与配对
    frozen: bool = False


@dataclass
class TPair:
    """一次做T(两腿)的记录

    开腿/收腿用中性字段表达,方向由 `direction` 决定:
      反T:open = 卖出,close = 买回
      正T:open = 买入,close = 卖出
    """

    direction: str
    status: str
    open_tx_id: int
    open_date: date
    open_price: Decimal
    # 这一段开腿对应的金额(= shares × open_price),清单聚合加权均价时用
    open_amount: Decimal = Decimal("0")
    close_tx_id: int | None = None
    close_date: date | None = None
    close_price: Decimal | None = None
    # 配对上的股数
    shares: int = 0
    # 开腿那一刻 / 收腿之后的摊薄成本
    cost_before: Decimal | None = None
    cost_after: Decimal | None = None
    # 做T差价盈亏 =(卖出价 − 买入价) × 股数
    t_pnl: Decimal | None = None
    # 卖出确认的已实现盈亏
    realized_pnl: Decimal | None = None

    @property
    def is_reverse(self) -> bool:
        return self.direction == DIRECTION_REVERSE

    @property
    def is_forward(self) -> bool:
        return self.direction == DIRECTION_FORWARD


# 链序流水的一行:(tx_id, action, shares, price, trade_date)
TxRow = tuple[int, str, int, Decimal, date]


def _close_pair(
    direction: str,
    leg: TLeg,
    tx_id: int,
    trade_date: date,
    price: Decimal,
    shares: int,
    cost_after: Decimal | None,
    cost_before_close: Decimal | None,
) -> TPair:
    """闭合一条开腿,算出两条腿的盈亏口径。"""
    if direction == DIRECTION_REVERSE:
        # 反T:开腿=卖出(已实现已确认),收腿=买入
        t_pnl = (leg.price - price) * shares
        realized = (
            (leg.price - leg.cost_before) * shares if leg.cost_before is not None else None
        )
    else:
        # 正T:开腿=买入,收腿=卖出(已实现此刻才确认)
        t_pnl = (price - leg.price) * shares
        realized = (
            (price - cost_before_close) * shares
            if cost_before_close is not None
            else None
        )
    return TPair(
        direction=direction,
        status=STATUS_CLOSED,
        open_tx_id=leg.tx_id,
        open_date=leg.trade_date,
        open_price=leg.price,
        open_amount=leg.price * shares,
        close_tx_id=tx_id,
        close_date=trade_date,
        close_price=price,
        shares=shares,
        cost_before=leg.cost_before,
        cost_after=cost_after,
        t_pnl=t_pnl,
        realized_pnl=realized,
    )


def pair_t_legs(
    rows: list[TxRow],
    cost_of: Callable[[int], tuple[Decimal | None, Decimal | None]],
    max_gap_days: int | None = T_PAIR_WINDOW_DAYS,
) -> list[TPair]:
    """把一条链的流水配成做T记录(双向 FIFO + 时间窗口)。

    rows 必须已按链全序(交易日, 时间点, id)排好。

    cost_of: 可调用对象 `cost_of(tx_id) -> (交易前摊薄成本 | None, 交易后摊薄成本 | None)`。
             没有成本基准的流水返回 (None, None) —— 成本字段留 null,不编数字。

    max_gap_days: 配对允许的最大间隔天数。None = 不限(不推荐,会把老加仓当成做T)。
                   超过窗口的开腿会被冻结,不再参与配对。
    """
    pending_sell: deque[TLeg] = deque()  # 反T开腿:已卖未买回
    pending_buy: deque[TLeg] = deque()  # 正T开腿:已买未卖出
    pairs: list[TPair] = []

    def _pick(
        queue: deque[TLeg], trade_date: date
    ) -> TLeg | None:
        """取队列里第一条「还没冻结且间隔在窗口内」的开腿。

        间隔超窗口的腿就地**冻结** —— 它与当前这笔相隔太久,不是一次做T,
        不能再跟后面的动作配对(否则「十月的买入」会吃掉「今天的卖出」)。
        """
        while queue:
            leg = queue[0]
            if leg.left <= 0:
                queue.popleft()
                continue
            if leg.frozen:
                return None
            if max_gap_days is not None and (trade_date - leg.trade_date).days > max_gap_days:
                leg.frozen = True
                queue.popleft()
                continue
            return leg
        return None

    for tx_id, action, shares, price, trade_date in rows:
        before, after = cost_of(tx_id)
        remaining = shares

        if action == "sell":
            # 1) 先闭合正T(先买后卖)
            while remaining > 0:
                leg = _pick(pending_buy, trade_date)
                if leg is None:
                    break
                take = min(leg.left, remaining)
                pairs.append(
                    _close_pair(
                        DIRECTION_FORWARD, leg, tx_id, trade_date, price, take, after, before
                    )
                )
                leg.left -= take
                leg.amount -= leg.price * take
                remaining -= take
                if leg.left <= 0:
                    pending_buy.remove(leg)
            # 2) 剩余部分成为反T开腿(已卖未买回)
            if remaining > 0:
                pending_sell.append(
                    TLeg(tx_id, trade_date, price, remaining, price * remaining, before)
                )
            continue

        # buy
        # 1) 先闭合反T(先卖后买)
        while remaining > 0:
            leg = _pick(pending_sell, trade_date)
            if leg is None:
                break
            take = min(leg.left, remaining)
            pairs.append(
                _close_pair(
                    DIRECTION_REVERSE, leg, tx_id, trade_date, price, take, after, before
                )
            )
            leg.left -= take
            leg.amount -= leg.price * take
            remaining -= take
            if leg.left <= 0:
                pending_sell.remove(leg)
        # 2) 剩余部分成为正T开腿(已买未卖出)
        if remaining > 0:
            pending_buy.append(
                TLeg(tx_id, trade_date, price, remaining, price * remaining, before)
            )

    # 链尾还挂着的开腿
    #
    # 窗口过滤:开腿日期必须落在「链上最后一天 − max_gap_days」之后。
    # 基准取链上最后一天(而不是「今天」)—— 确定性,不随时间漂移,历史数据也能算。
    # 窗口外的老加仓不是「正在做的T」,不该占着提醒清单的位置。
    anchor = rows[-1][4] if rows else None
    window_start = (
        anchor - timedelta(days=max_gap_days)
        if anchor is not None and max_gap_days is not None
        else None
    )

    def _in_window(leg: TLeg) -> bool:
        return window_start is None or leg.trade_date >= window_start

    for leg in pending_sell:
        if leg.left <= 0 or not _in_window(leg):
            continue
        pairs.append(
            TPair(
                direction=DIRECTION_REVERSE,
                status=STATUS_PENDING,
                open_tx_id=leg.tx_id,
                open_date=leg.trade_date,
                open_price=leg.price,
                open_amount=leg.price * leg.left,
                shares=leg.left,
                cost_before=leg.cost_before,
                cost_after=None,
                t_pnl=None,
                # 卖出那一刻已实现就已经确认了 —— 即使还没买回
                realized_pnl=(
                    (leg.price - leg.cost_before) * leg.left
                    if leg.cost_before is not None
                    else None
                ),
            )
        )
    for leg in pending_buy:
        if leg.left <= 0 or not _in_window(leg):
            continue
        pairs.append(
            TPair(
                direction=DIRECTION_FORWARD,
                status=STATUS_PENDING,
                open_tx_id=leg.tx_id,
                open_date=leg.trade_date,
                open_price=leg.price,
                open_amount=leg.price * leg.left,
                shares=leg.left,
                cost_before=leg.cost_before,
                cost_after=None,
                t_pnl=None,
                # 还没卖 → 已实现还没确认
                realized_pnl=None,
            )
        )

    return pairs
