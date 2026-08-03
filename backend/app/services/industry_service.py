"""M2.1 行业归属服务(三级兜底)

1. 一级:离线行业表(baostock 生成, app/data/industry_map.json,运行时纯只读)
   覆盖沪深 A 股证监会行业分类。北交所等可能未覆盖。
2. 二级:新浪行业板块排行领涨股反查(覆盖一级未命中的股)
3. 三级:仍未命中 → 降级返回 industry=None + 提示,不造假
"""
import json
import logging
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from app.services.sector_fund_flow_service import get_sector_fund_flow

logger = logging.getLogger(__name__)

_MAP_PATH = Path(__file__).resolve().parents[1] / "data" / "industry_map.json"
_SINA_FENLEI = 1
_SINA_NUM = 60


@lru_cache(maxsize=1)
def _load_industry_map() -> dict[str, str]:
    """读离线表:内部代码 → 行业名;表缺失/损坏回退空 dict"""
    if not _MAP_PATH.exists():
        logger.warning("离线行业表不存在: %s", _MAP_PATH)
        return {}
    try:
        raw = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("离线行业表解析失败: %s", e)
        return {}
    out: dict[str, str] = {}
    for code, info in raw.items():
        name = info.get("name") if isinstance(info, dict) else None
        if name:
            out[code] = name
    return out


def match_sina_industry_rank(items: Iterable[dict], stock_code: str) -> dict | None:
    """从板块排行反查该股是否为某行业领涨股(纯函数,可单测)

    Returns: {name} 或 None
    """
    for it in items:
        top = it.get("top_stock") or {}
        if top.get("code") == stock_code:
            return {"name": it.get("name", "")}
    return None


def _resolve_local(code: str) -> str | None:
    """一级:离线表查询,未命中返回 None"""
    return _load_industry_map().get(code)


async def _resolve_sina(code: str) -> str | None:
    """二级:新浪行业排行领涨反查,失败/未命中返回 None"""
    try:
        items = await get_sector_fund_flow(fenlei=_SINA_FENLEI, num=_SINA_NUM, sort="netamount")
    except Exception as e:  # noqa: BLE001
        logger.warning("新浪行业排行失败(%s): %s", code, e)
        return None
    hit = match_sina_industry_rank(items, code)
    return hit["name"] if hit else None


async def resolve_industry(code: str) -> dict:
    """三级兜底;返回 {code, industry, source, note}"""
    name = _resolve_local(code)
    if name:
        return {
            "code": code,
            "industry": name,
            "source": "baostock",
            "note": None,
        }

    name = await _resolve_sina(code)
    if name:
        return {
            "code": code,
            "industry": name,
            "source": "sina",
            "note": "新浪行业排行领涨股命中(离线表未覆盖)",
        }

    return {
        "code": code,
        "industry": None,
        "source": None,
        "note": "未获得行业归属(离线表外/北交所),行业走势暂不可用",
    }


__all__ = ["resolve_industry", "match_sina_industry_rank", "_load_industry_map"]