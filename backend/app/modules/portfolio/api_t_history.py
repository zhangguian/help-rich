"""做T操作历史 API

口径(单一,不搞多套推断):
  做T有**两个方向**,腿的先后顺序不同(见 `t_pairing.py`):

  | 方向 | 中文 | 开腿 | 收腿 |
  |------|------|------|------|
  | 反T  | reverse | 卖出(先卖) | 买回(后买) |
  | 正T  | forward | 买入(先买) | 卖出(后卖) |

  配对按链全序(交易日, 时间点, id)双向 FIFO 走一遍:
  后一笔流水优先闭合最早的开腿;链尾还挂着的开腿 = 待接回(反T) / 待卖出(正T)。

  每条记录给两个盈亏口径:
  - `t_pnl`       做T差价盈亏 = (卖出价 − 买入价) × T股数
                  —— 两个方向都是「低买高卖赚差价」,正数 = 这波做T赚钱了。
                  还没闭合时价差还不存在,为 null(不编数字)。
  - `realized_pnl` 卖出确认的已实现盈亏 = (卖出价 − 卖出那一刻的摊薄成本) × T股数
                  —— 反T在卖出时确认,正T在卖出时(收腿)确认。

  成本价取自**成本链**(基准 + 活链重放,摊薄口径):
  - `cost_before` 开腿那一刻的持仓摊薄成本
  - `cost_after`  收腿之后的持仓摊薄成本
  基准吸收掉的早期流水(id <= base_tx_id)没有逐笔成本快照,这两个字段为 null。

  口径边界:配对范围是**全部流水**(含基准吸收段),成本字段只在活链段有值。

  GET /api/t-history/{stock_code} → 该标的的做T历史(最近的在最前)
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.logging import logger
from app.modules.portfolio.service import (
    ChainState,
    PositionChainError,
    TxSpec,
    apply_transaction,
    load_chain_context,
)
from app.modules.portfolio.t_pairing import (
    DIRECTION_REVERSE,
    TPair,
    pair_t_legs,
)

router = APIRouter(prefix="/t-history", tags=["t-history"])


class THistoryItem(BaseModel):
    """一次做T(两腿)的记录

    字段用「卖出那笔 / 买入那笔」的中性语义表达,方向看 `direction`:
      反T:sell_* = 开腿(卖出),buy_* = 收腿(买回)
      正T:buy_* = 开腿(买入),sell_* = 收腿(卖出)
    """

    status: str
    # 做T方向:reverse = 反T(先卖后买) / forward = 正T(先买后卖)
    direction: str
    # 卖出腿
    sell_tx_id: int | None = None
    sell_date: str | None = None
    sell_price: float | None = None
    # 买回腿
    buy_tx_id: int | None = None
    buy_date: str | None = None
    buy_price: float | None = None
    # 做T股数(配对上的那一段)
    shares: int
    # T 前成本价(开腿那一刻的持仓摊薄成本)
    cost_before: float | None = None
    # T 后成本价(收腿之后的持仓摊薄成本)
    cost_after: float | None = None
    # 做T差价盈亏 =(卖出价 − 买入价) × 股数
    t_pnl: float | None = None
    # 卖出确认的已实现盈亏
    realized_pnl: float | None = None


class THistoryOut(BaseModel):
    stock_code: str
    stock_name: str | None = None
    items: list[THistoryItem]
    count: int
    # 基准吸收的流水 id 上界 —— <= 它的流水没有逐笔成本,成本字段为 null
    base_tx_id: int


def _f3(d: Decimal | None) -> float | None:
    """量化到 3 位(与成本价口径一致)"""
    if d is None:
        return None
    return float(d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def _f2(d: Decimal | None) -> float | None:
    """量化到 2 位(金额口径)"""
    if d is None:
        return None
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _chain_state_map(
    base: ChainState,
    chain: list[TxSpec],
) -> dict[int, tuple[ChainState | None, ChainState]]:
    """活链每笔流水的 (交易前状态, 交易后状态)。

    基准吸收段(id <= base_tx_id)的流水不在这里 —— 它们没有逐笔成本快照。
    """
    out: dict[int, tuple[ChainState | None, ChainState]] = {}
    state = base
    for spec in chain:
        before = state
        try:
            state = apply_transaction(state, spec.action, spec.shares, spec.price)
        except PositionChainError as e:
            # 链不自洽(卖出超过当时持仓)→ 这条标的没有可信成本,记录降级
            logger.warning(f"[t-history] {spec.stock_name or ''} 链重放失败 id={spec.id}: {e}")
            return {}
        out[spec.id] = (before, state)
    return out


def _to_item(pair: TPair) -> THistoryItem:
    """把配对结果映射成对外字段(卖出那笔 / 买入那笔)"""
    is_reverse = pair.direction == DIRECTION_REVERSE
    sell_tx_id = pair.open_tx_id if is_reverse else pair.close_tx_id
    sell_date = pair.open_date if is_reverse else pair.close_date
    sell_price = pair.open_price if is_reverse else pair.close_price
    buy_tx_id = pair.close_tx_id if is_reverse else pair.open_tx_id
    buy_date = pair.close_date if is_reverse else pair.open_date
    buy_price = pair.close_price if is_reverse else pair.open_price
    return THistoryItem(
        status=pair.status,
        direction=pair.direction,
        sell_tx_id=sell_tx_id,
        sell_date=sell_date.isoformat() if sell_date else None,
        sell_price=_f3(sell_price),
        buy_tx_id=buy_tx_id,
        buy_date=buy_date.isoformat() if buy_date else None,
        buy_price=_f3(buy_price),
        shares=pair.shares,
        cost_before=_f3(pair.cost_before),
        cost_after=_f3(pair.cost_after),
        t_pnl=_f2(pair.t_pnl),
        realized_pnl=_f2(pair.realized_pnl),
    )


@router.get("/{stock_code}", response_model=THistoryOut)
async def get_t_history(stock_code: str) -> THistoryOut:
    """某只票的做T历史记录(含正T / 反T)。

    链重放失败(卖出超过当时持仓)时降级: 不给成本价,只给能算的价差。
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    code = stock_code.strip().upper()
    base, chain, tx_rows, base_tx_id = await load_chain_context(code, DEFAULT_ACCOUNT_ID)

    # 活链逐笔状态(基准吸收段没有 → 成本字段 null)
    state_map = _chain_state_map(base, chain)

    def cost_of(tx_id: int) -> tuple[Decimal | None, Decimal | None]:
        states = state_map.get(tx_id)
        if not states:
            return (None, None)
        return (states[0].avg_cost, states[1].avg_cost)

    rows = [
        (tx.id, tx.action, int(tx.shares), Decimal(tx.price), tx.trade_date)
        for tx in tx_rows
    ]
    pairs = pair_t_legs(rows, cost_of)
    items = [_to_item(p) for p in pairs]

    # 最近的在最前(按「最后一次动作」的日期倒序 —— 闭合的T以收腿那天为准)
    items.sort(
        key=lambda it: (
            max(it.sell_date or "", it.buy_date or ""),
            max(it.sell_tx_id or 0, it.buy_tx_id or 0),
        ),
        reverse=True,
    )

    stock_name = next((t.stock_name for t in reversed(tx_rows) if t.stock_name), None)

    return THistoryOut(
        stock_code=code,
        stock_name=stock_name,
        items=items,
        count=len(items),
        base_tx_id=base_tx_id,
    )
