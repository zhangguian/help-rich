"""stock_code 规范化测试(P3.5.1)

覆盖:
- 纯 6 位数字推断市场(6/9→SH,0/1/2/3→SZ,4/8→BJ)
- 带后缀格式(大小写)
- 前缀格式(sh/sz/bj)
- 非法输入(5 位/字母/未知市场)
"""
from app.core.stock_code import infer_market, normalize_code


class TestNormalizeCode:
    def test_pure_six_digits(self):
        assert normalize_code("600519") == "600519.SH"
        assert normalize_code("900901") == "900901.SH"
        assert normalize_code("000001") == "000001.SZ"
        assert normalize_code("300750") == "300750.SZ"
        assert normalize_code("200002") == "200002.SZ"
        assert normalize_code("830799") == "830799.BJ"
        assert normalize_code("430300") == "430300.BJ"

    def test_with_suffix_uppercase(self):
        assert normalize_code("600519.SH") == "600519.SH"
        assert normalize_code("000001.SZ") == "000001.SZ"
        assert normalize_code("830799.BJ") == "830799.BJ"

    def test_with_suffix_lowercase(self):
        assert normalize_code("600519.sh") == "600519.SH"
        assert normalize_code("000001.sz") == "000001.SZ"

    def test_prefix_format(self):
        assert normalize_code("sh600519") == "600519.SH"
        assert normalize_code("sz000001") == "000001.SZ"
        assert normalize_code("bj830799") == "830799.BJ"

    def test_whitespace_stripped(self):
        assert normalize_code(" 600519.SH ") == "600519.SH"

    def test_invalid_inputs(self):
        assert normalize_code("") is None
        assert normalize_code("12345") is None  # 5 位
        assert normalize_code("1234567") is None  # 7 位
        assert normalize_code("abcdef") is None  # 字母
        assert normalize_code("600519.XX") is None  # 未知市场
        assert normalize_code("600519.SH.extra") is None  # 多余后缀
        assert normalize_code(None) is None


class TestInferMarket:
    def test_markets(self):
        assert infer_market("600519") == "SH"
        assert infer_market("000001") == "SZ"
        assert infer_market("830799") == "BJ"

    def test_invalid(self):
        assert infer_market("12345") is None
