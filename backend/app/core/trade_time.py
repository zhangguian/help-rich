"""交易时间节点的解析 / 格式化(纯函数)

流水新增「时间点」字段(trade_time)后,字符串与 datetime.time 的转换集中在
这里,避免各处各写一份正则。

口径:
- 存储:datetime.time(HH:MM:SS)
- 传输:字符串 "HH:MM" 或 "HH:MM:SS"
- 未知 = None(**不编造**):存量流水、用户留空、截图导入都走这个分支
"""
from __future__ import annotations

from datetime import time


def parse_trade_time(value: str | None) -> time | None:
    """字符串 → time;空 / 非法 → None(未知)

    非法值一律降级为 None 而不是抛错 —— 时间点只影响排序与评分维度,
    录入本身不该因为格式细节被拒(入参校验在 schema 层做)。
    """
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    parts = v.split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2]) if len(parts) == 3 else 0
        return time(hour=hh, minute=mm, second=ss)
    except ValueError:
        return None


def format_trade_time(value: time | None) -> str | None:
    """time → "HH:MM:SS";None → None"""
    if value is None:
        return None
    return value.strftime("%H:%M:%S")


__all__ = ["parse_trade_time", "format_trade_time"]
