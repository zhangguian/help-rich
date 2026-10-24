"""标的品种识别(场内 ETF / 股票)

**为什么需要这一层**:同一套「持仓 → 成本 → 决策 → 做 T」链路里,ETF 与股票的
交易规则不同,拿股票规则套 ETF 会给出**事实错误**的结论:

| 规则 | 股票 | 场内 ETF |
|---|---|---|
| 印花税 | 卖出 0.05% | **免** |
| 过户费 | 双向 0.001% | **免** |
| 涨跌幅限制 | ±10%/±20%/±5% | **无**(ETF 无涨跌停) |
| 当日回转 | T+1(当天买当天不能卖) | 境内股票ETF T+1;跨境/黄金/商品 ETF **T+0** |

**判定顺序**(先表后格式):
1. 命中静态表 `data/etf_instruments.json` → ETF,带类别/跟踪指数/T+0 属性
2. 表外但代码符合 ETF 格式 → ETF,但 `known=False`,**保守按 T+1 处理**
   (无据不判 T+0 —— 跨境 513100 与境内 510300 都是 51 开头,前缀分不开)
3. 其余 → 股票

**表外 ETF 必须显式降级**:判定层要把它写进 `degraded`,而不是假装已知。
(「未填写 ≠ 0」的同款原则:「不知道」和「按保守口径」是两件事。)

**依赖方向**:本模块在 `core/`,只读静态 JSON + 纯函数,不得依赖业务层
(见 tests/test_architecture_boundaries.py::test_core_does_not_depend_on_business_layers)。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.cost_engine import TradeFees

logger = logging.getLogger(__name__)

_INSTRUMENTS_PATH = Path(__file__).resolve().parents[1] / "data" / "etf_instruments.json"

KIND_STOCK = "stock"
KIND_ETF = "etf"

# 场内 ETF/LOF 的代码格式(与 core/stock_code.py 的市场前缀规则一致):
#   5xxxxx.SH → 沪市 ETF(51/56/58 系列)
#   1xxxxx.SZ → 深市 ETF/LOF(15/16 系列)
_ETF_CODE_RE = re.compile(r"^(5\d{5}\.SH|1\d{5}\.SZ)$")

# 表外 ETF 的降级说明(判定层写进 degraded,不给假数字、不假装已知)
UNKNOWN_ETF_NOTE = (
    "该 ETF 未在品种表内,已按保守口径(T+1 / 股票费率)计算,交易规则可能有偏差"
)


@dataclass(frozen=True)
class Instrument:
    """一个标的的品种属性(纯数据)"""

    code: str
    kind: str                      # 'stock' | 'etf'
    category: str | None = None    # broad/industry/qdii/commodity/bond/money
    category_label: str | None = None   # 宽基/行业/QDII/商品/债券/货币
    index_name: str | None = None  # 跟踪指数名
    display_name: str | None = None    # 场内简称
    t0: bool = False               # 是否当日可回转(T+0)
    known: bool = False            # True = 命中品种表; False = 表外按格式判定

    @property
    def is_etf(self) -> bool:
        return self.kind == KIND_ETF


@lru_cache(maxsize=1)
def _load_table() -> tuple[dict[str, dict], dict[str, str]]:
    """读静态品种表 → (code → 条目, category → 中文标签)

    表缺失/损坏 → 回退空表(不抛错)。此时所有代码走「格式判定」路径,
    表外 ETF 的 `known=False` → 保守 T+1 + 降级说明。
    """
    if not _INSTRUMENTS_PATH.exists():
        logger.warning("品种规则表不存在: %s", _INSTRUMENTS_PATH)
        return {}, {}
    try:
        raw = json.loads(_INSTRUMENTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("品种规则表解析失败: %s", e)
        return {}, {}
    items: dict[str, dict] = {}
    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip().upper()
        if not code:
            continue
        # t0 缺失时按 false(保守)处理 —— 判错 T+0 会给出错误的上限
        items[code] = {
            "index": item.get("index"),
            "name": item.get("name"),
            "category": item.get("category"),
            "t0": bool(item.get("t0", False)),
        }
    labels = {
        str(k): str(v)
        for k, v in (raw.get("categories") or {}).items()
        if isinstance(v, str)
    }
    return items, labels


def resolve_instrument(code: str) -> Instrument:
    """按品种表 + 代码格式判定标的品种(纯函数,可单测)"""
    normalized = (code or "").strip().upper()
    items, labels = _load_table()
    row = items.get(normalized)
    if row is not None:
        category = row.get("category")
        return Instrument(
            code=normalized,
            kind=KIND_ETF,
            category=category,
            category_label=labels.get(str(category)) if category else None,
            index_name=row.get("index"),
            display_name=row.get("name"),
            t0=bool(row.get("t0")),
            known=True,
        )
    if _ETF_CODE_RE.match(normalized):
        # 表外 ETF:保守按 T+1(无据不判 T+0)
        return Instrument(code=normalized, kind=KIND_ETF, t0=False, known=False)
    return Instrument(code=normalized, kind=KIND_STOCK)


def fees_for_instrument(code: str, base: TradeFees | None) -> TradeFees | None:
    """按品种返回费用档;None 原样返回(费用被禁用)

    ETF 免印花税、免过户费(法规),佣金沿用用户配置。
    """
    if base is None:
        return None
    if resolve_instrument(code).is_etf:
        return TradeFees.etf_variant(base)
    return base


def degraded_note(code: str) -> str | None:
    """该标的的降级说明(没有就返回 None)"""
    inst = resolve_instrument(code)
    if inst.is_etf and not inst.known:
        return UNKNOWN_ETF_NOTE
    return None


__all__ = [
    "Instrument",
    "KIND_ETF",
    "KIND_STOCK",
    "UNKNOWN_ETF_NOTE",
    "degraded_note",
    "fees_for_instrument",
    "resolve_instrument",
]
