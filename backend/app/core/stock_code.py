"""股票代码规范化工具(P3.5.1)

统一内部格式:600519.SH / 000001.SZ / 830799.BJ(见 data-source-guide §1.1)
市场推断规则:
  5xxxxx → SH(沪市 ETF:51/56/58 系列)
  6xxxxx → SH(沪市主板)
  9xxxxx → SH(B 股)
  0xxxxx → SZ(深市主板)
  1xxxxx → SZ(深市 ETF/基金/债券:15/16 系列)
  2xxxxx → SZ(B 股)
  3xxxxx → SZ(创业板)
  4xxxxx → BJ(北交所)
  8xxxxx → BJ(北交所)
"""

# 合法市场后缀
VALID_MARKETS = {"SH", "SZ", "BJ"}

# 前缀 → 市场
_MARKET_BY_PREFIX: list[tuple[str, str]] = [
    ("5", "SH"),
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


# 沪深主板的代码前缀(按市场分)
#   SH 主板:600(主板)/601/603/605(次新主板代码段)
#   SZ 主板:000/001/002/003(原中小板已并入主板)
# 刻意**不含**:
#   300/301 创业板、688/689 科创板、8xx/4xx/920 北交所、900/200 B 股
MAIN_BOARD_PREFIXES: dict[str, tuple[str, ...]] = {
    "SH": ("600", "601", "603", "605"),
    "SZ": ("000", "001", "002", "003"),
}


def is_main_board(code: str) -> bool:
    """该代码是否属于**沪深主板**(不含创业板 / 科创板 / 北交所 / B 股)

    纯函数、零 IO —— 选股 universe 的第一道闸门。

    为什么按**代码前缀**而不是按市场后缀判:
    `infer_market` 只能区分 SH/SZ/BJ,分不出「主板 vs 创业板 vs 科创板」
    —— 那三个都在 SH/SZ 里。板块差异必须落到代码段上。

    输入接受任意格式(600519 / 600519.SH / sh600519),非法返回 False。
    """
    normalized = normalize_code(code)
    if not normalized:
        return False
    num, market = normalized.split(".")
    return num.startswith(MAIN_BOARD_PREFIXES.get(market, ()))
