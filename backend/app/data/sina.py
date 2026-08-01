"""新浪实时行情客户端(arch §5.5.2 优先级第一,data-source-guide §1.2)

接口: https://hq.sinajs.cn/list=sh600519,sz000001
编码: GBK(中文字段名 GBK 编码)
限流: 需 Referer 头,单次最多 ~50 只
字段: 0名称 1今开 2昨收 3最新价 4最高 5最低 6买一价 7卖一价
      8成交量(股) 9成交额(元) 10~29五档 30日期 31时间
"""
import re
import decimal
from datetime import datetime
from decimal import Decimal

import httpx

from app.data.base import DataSource
from app.data.unified import UnifiedQuote

SINA_URL = "https://hq.sinajs.cn/list="
SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://finance.sina.com.cn",
}

# hq_str_sh600519="名称,今开,昨收,最新价,...";
_PATTERN = re.compile(r'hq_str_(sh|sz|bj)(\d{6})="([^"]*)"')


def _market_prefix(code: str) -> str:
    """内部 600519.SH → 新浪 sh600519"""
    num, market = code.split(".")
    return f"{market.lower()}{num}"


def _to_internal(prefix: str, num: str) -> str:
    market = {"sh": "SH", "sz": "SZ", "bj": "BJ"}[prefix]
    return f"{num}.{market}"


class SinaClient(DataSource):
    """新浪实时行情(MVP 主数据源)"""

    name = "sina"

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            headers=SINA_HEADERS,
            timeout=8.0,
            trust_env=False,  # 公司网络代理会导致 TLS 被断开,直连
        )

    async def get_quote(self, code: str) -> UnifiedQuote:
        quotes = await self.get_quotes([code])
        return quotes[0]

    async def get_quotes(self, codes: list[str]) -> list[UnifiedQuote]:
        # 新浪单请求最多 ~50 只,超出分片
        results: list[UnifiedQuote] = []
        for i in range(0, len(codes), 50):
            chunk = codes[i : i + 50]
            symbols = ",".join(_market_prefix(c) for c in chunk)
            resp = await self._client.get(SINA_URL + symbols)
            resp.raise_for_status()
            text = resp.content.decode("gbk", errors="replace")
            found = {c: None for c in chunk}
            for m in _PATTERN.finditer(text):
                prefix, num, payload = m.groups()
                if not payload:  # 停牌/退市等无数据
                    continue
                internal = _to_internal(prefix, num)
                found[internal] = self._parse(internal, payload)
            results.extend(q for q in found.values() if q is not None)
        return results

    @staticmethod
    def _parse(code: str, payload: str) -> UnifiedQuote | None:
        f = payload.split(",")
        if len(f) < 32 or not f[3]:
            return None
        try:
            current = Decimal(f[3])
            prev_close = Decimal(f[2])
            return UnifiedQuote(
                code=code,
                name=f[0],
                current_price=current,
                prev_close=prev_close,
                open=Decimal(f[1]),
                high=Decimal(f[4]),
                low=Decimal(f[5]),
                change=current - prev_close,
                change_pct=float(current / prev_close * 100 - 100) if prev_close else 0.0,
                volume=int(Decimal(f[8])),
                amount=Decimal(f[9]),
                timestamp=datetime.now(),
            )
        except (ValueError, decimal.InvalidOperation):
            return None
