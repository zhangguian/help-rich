"""股票代码规范化工具(P3.5.1)

统一内部格式:600519.SH / 000001.SZ / 830799.BJ(见 data-source-guide §1.1)
市场推断规则:
  6xxxxx → SH(沪市主板)
  9xxxxx → SH(B 股)
  0xxxxx → SZ(深市主板)
  1xxxxx → SZ(深市基金/债券,少量)
  2xxxxx → SZ(B 股)
  3xxxxx → SZ(创业板)
  4xxxxx → BJ(北交所)
  8xxxxx → BJ(北交所)
"""

# 合法市场后缀
VALID_MARKETS = {"SH", "SZ", "BJ"}

# 前缀 → 市场
_MARKET_BY_PREFIX: list[tuple[str, str]] = [
    ("6", "SH"),
    ("9", "SH"),
    ("0", "SZ"),
    ("1", "SZ"),
    ("2", "SZ"),
    ("3", "SZ"),
    ("4", "BJ"),
    ("8", "BJ"),
]


def normalize_code(code: str) -> str | None:
    """任意格式 → 带后缀统一格式;非法返回 None

    支持输入:600519 / 600519.SH / sh600519 / 600519.SH(任意大小写)
    """
    if not code:
        return None
    code = code.strip().lower()
    # 去掉 sh/sz/bj 前缀(小写已转)
    if code[:2] in ("sh", "sz", "bj") and len(code) >= 8:
        code = code[2:]
    # 去掉 .sh/.sz/.bj 后缀
    if "." in code:
        parts = code.split(".")
        if len(parts) != 2:
            return None
        num, market = parts
        if not (len(num) == 6 and num.isdigit()):
            return None
        market = market.upper()
        if market not in VALID_MARKETS:
            return None
        return f"{num}.{market}"
    # 纯 6 位数字 → 推断市场
    if len(code) == 6 and code.isdigit():
        for prefix, market in _MARKET_BY_PREFIX:
            if code.startswith(prefix):
                return f"{code}.{market}"
    return None


def infer_market(num: str) -> str | None:
    """6 位数字 → 市场后缀(SH/SZ/BJ),非法返回 None"""
    normalized = normalize_code(num)
    if normalized:
        return normalized.split(".")[1]
    return None
