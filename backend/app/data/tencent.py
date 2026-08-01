"""腾讯实时行情客户端(arch §5.5.2 备选数据源)

接口: https://qt.gtimg.cn/q=sh600519,sz000001
编码: GBK(中文字段名 GBK 编码)
字段(以 ~ 分隔):
 0市场 1名称 2代码 3最新价 4昨收 5今开 6成交量(手) 7外盘 8内盘
 9~28 五档买卖(买一价~卖五量)
 29时间(yyyyMMddHHmmss) 30(空) 31涨跌 32涨跌% 33最高 34最低
 35现价/成交量(手)/成交额 36成交量(手) 37成交额(万)
 38换手率 39PE 40(空) 41最高 42最低 43振幅
 44流通市值(亿) 45总市值(亿) 46PB
"""
import re
import decimal
from datetime import datetime
from decimal import Decimal

import httpx

from app.data.base import DataSource
from app.data.unified import UnifiedQuote

TENCENT_URL = "https://qt.gtimg.cn/q="
TENCENT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}

# v_sh600519="1~贵州茅台~600519~...";
_PATTERN = re.compile(r'v_(sh|sz|bj)(\d{6})="([^"]*)"')


def _market_prefix(code: str) -> str:
    num, market = code.split(".")
    return f"{market.lower()}{num}"


def _to_internal(prefix: str, num: str) -> str:
    market = {"sh": "SH", "sz": "SZ", "bj": "BJ"}[prefix]
    return f"{num}.{market}"


class TencentClient(DataSource):
    """腾讯实时行情(MVP 备选数据源,新浪失败时降级)"""

    name = "tencent"

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            headers=TENCENT_HEADERS,
            timeout=8.0,
            trust_env=False,
        )

    async def get_quote(self, code: str) -> UnifiedQuote:
        quotes = await self.get_quotes([code])
        return quotes[0]

    async def get_quotes(self, codes: list[str]) -> list[UnifiedQuote]:
        # 腾讯单请求支持多只,无明确上限,全量一次
        symbols = ",".join(_market_prefix(c) for c in codes)
        resp = await self._client.get(TENCENT_URL + symbols)
        resp.raise_for_status()
        text = resp.content.decode("gbk", errors="replace")
        found = {c: None for c in codes}
        for m in _PATTERN.finditer(text):
            prefix, num, payload = m.groups()
            if not payload:
                continue
            internal = _to_internal(prefix, num)
            found[internal] = self._parse(internal, payload)
        return [q for q in found.values() if q is not None]

    @staticmethod
    def _parse(code: str, payload: str) -> UnifiedQuote | None:
        f = payload.split("~")
        if len(f) < 46 or not f[3]:
            return None
        try:
            current = Decimal(f[3])
            prev_close = Decimal(f[4])
            volume_lots = int(Decimal(f[6]))  # 手,转股
            return UnifiedQuote(
                code=code,
                name=f[1],
                current_price=current,
                prev_close=prev_close,
                open=Decimal(f[5]),
                high=Decimal(f[33]),
                low=Decimal(f[34]),
                change=current - prev_close,
                change_pct=float(f[32]) if f[32] else 0.0,
                volume=volume_lots * 100,
                amount=Decimal(f[37]) * Decimal("10000"),  # 万 → 元
                timestamp=datetime.now(),
                turnover_pct=float(f[38]) if f[38] else None,
                pe=float(f[39]) if f[39] else None,
                pb=float(f[46]) if f[46] else None,
            )
        except (ValueError, decimal.InvalidOperation):
            return None
