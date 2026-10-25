"""标的品种识别测试(场内 ETF / 股票)

**为什么单独建文件**:品种判定是 ETF 全部交易规则的入口 ——
判错 `kind` 会让费用、T+0 提示、做 T 上限一起错。
所以这里锁住三件事:
1. 表内命中 / 表外格式判定 / 股票不误判
2. 表外 ETF **保守按 T+1**(无据不判 T+0 —— 513100 与 510300 前缀分不开)
3. 表缺失时降级而不抛错
"""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.cost_engine import TradeFees
from app.core.instrument import (
    KIND_ETF,
    KIND_STOCK,
    UNKNOWN_ETF_NOTE,
    degraded_note,
    fees_for_instrument,
    resolve_instrument,
)

_BACKEND_TABLE = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "etf_instruments.json"
)


def _backend_table() -> dict:
    return json.loads(_BACKEND_TABLE.read_text(encoding="utf-8"))


def _backend_items() -> list[dict]:
    return list(_backend_table().get("items") or [])


def _backend_categories() -> dict:
    return dict(_backend_table().get("categories") or {})


class TestResolveInstrument:
    def test_table_hit_domestic_etf(self):
        """510300(沪深300ETF)→ etf / 境内 / T+1 / 命中表"""
        inst = resolve_instrument("510300.SH")
        assert inst.kind == KIND_ETF
        assert inst.known is True
        assert inst.t0 is False
        assert inst.index_name == "沪深 300"
        assert inst.category == "broad"
        assert inst.category_label == "宽基"

    def test_table_hit_qdii_etf_is_t0(self):
        """513100(纳指ETF)→ 跨境,T+0"""
        inst = resolve_instrument("513100.SH")
        assert inst.kind == KIND_ETF
        assert inst.known is True
        assert inst.t0 is True
        assert inst.category == "qdii"
        assert inst.category_label == "QDII"

    def test_table_hit_gold_etf_is_t0(self):
        """518880(黄金ETF)→ 商品,T+0"""
        inst = resolve_instrument("518880.SH")
        assert inst.kind == KIND_ETF
        assert inst.t0 is True
        assert inst.category == "commodity"

    def test_stock_is_not_etf(self):
        """普通股票不受影响"""
        for code in ("600519.SH", "000001.SZ", "300750.SZ", "002185.SZ", "830799.BJ"):
            inst = resolve_instrument(code)
            assert inst.kind == KIND_STOCK, code
            assert inst.t0 is False
            assert inst.known is False

    def test_etf_outside_table_is_etf_but_conservative(self):
        """表外 ETF:按格式判定为 etf,但 known=False 且保守按 T+1"""
        inst = resolve_instrument("510999.SH")
        assert inst.kind == KIND_ETF
        assert inst.known is False
        assert inst.t0 is False
        assert inst.category is None
        assert inst.index_name is None

    def test_sz_etf_format_detected(self):
        """深市 15/16 系列也算 ETF 格式"""
        assert resolve_instrument("159999.SZ").kind == KIND_ETF
        assert resolve_instrument("160999.SZ").kind == KIND_ETF

    def test_case_and_suffix_insensitive(self):
        """大小写/空白不影响判定"""
        assert resolve_instrument(" 510300.sh ").kind == KIND_ETF
        assert resolve_instrument("513100.sh").t0 is True


class TestDegradedNote:
    def test_unknown_etf_gets_note(self):
        note = degraded_note("510999.SH")
        assert note == UNKNOWN_ETF_NOTE
        assert "未在品种表内" in note

    def test_known_etf_has_no_note(self):
        assert degraded_note("510300.SH") is None

    def test_stock_has_no_note(self):
        assert degraded_note("600519.SH") is None


class TestFees:
    def _base(self) -> TradeFees:
        return TradeFees(
            enabled=True,
            commission_rate=Decimal("0.00025"),
            min_commission=Decimal("5.00"),
            stamp_tax_rate=Decimal("0.0005"),
            transfer_fee_rate=Decimal("0.00001"),
        )

    def test_etf_variant_zeroes_tax_and_transfer_fee(self):
        """ETF:免印花税、免过户费;佣金沿用"""
        f = TradeFees.etf_variant(self._base())
        assert f.stamp_tax_rate == 0
        assert f.transfer_fee_rate == 0
        assert f.commission_rate == Decimal("0.00025")
        assert f.min_commission == Decimal("5.00")
        assert f.enabled is True

    def test_fees_for_instrument_switches_by_kind(self):
        base = self._base()
        etf_fees = fees_for_instrument("510300.SH", base)
        assert etf_fees is not None
        assert etf_fees.stamp_tax_rate == 0

        stock_fees = fees_for_instrument("600519.SH", base)
        assert stock_fees is not None
        assert stock_fees.stamp_tax_rate == Decimal("0.0005")
        assert stock_fees.transfer_fee_rate == Decimal("0.00001")

    def test_none_base_stays_none(self):
        """费用被禁用时保持 None(不构造一个 enabled=False 的替身)"""
        assert fees_for_instrument("510300.SH", None) is None


class TestTableIntegrity:
    """表本身的完整性 —— 品种表是手工维护的数据文件,最容易出的错是「重复/写错」"""

    def test_codes_are_unique(self):
        codes = [i["code"] for i in _backend_items()]
        assert len(codes) == len(set(codes)), "品种表存在重复代码"

    def test_every_item_has_required_fields(self):
        for it in _backend_items():
            assert it.get("code"), it
            assert it.get("name"), it
            assert it.get("index"), it
            assert it.get("category") in _backend_categories(), it
            assert isinstance(it.get("t0"), bool), it

    def test_t0_only_for_cross_border_or_commodity(self):
        """T+0 只对跨境(QDII)/商品成立 —— 境内股票 ETF 标了 T+0 就是错的"""
        for it in _backend_items():
            if it.get("t0"):
                assert it.get("category") in ("qdii", "commodity"), it

    def test_lof_entries_marked_and_default_is_etf(self):
        """场内 LOF 标注 form=lof;缺省按 etf"""
        assert resolve_instrument("162411.SZ").is_lof is True
        assert resolve_instrument("501099.SH").is_lof is True
        assert resolve_instrument("510300.SH").is_lof is False
        assert resolve_instrument("510300.SH").form == "etf"

    def test_watchlist_etfs_are_covered(self):
        """用户自选里的 ETF 必须能被识别(否则徽章全是「表外灰」)"""
        expect_t0 = {
            "513180.SH": True,   # 恒生科技 ETF(QDII)
            "513120.SH": True,   # 港股创新药 ETF(QDII)
            "159981.SZ": True,   # 能源化工 ETF(商品期货)
            "159732.SZ": False,  # 消费电子
            "588160.SH": False,  # 科创新材料
            "561380.SH": False,  # 电网设备
            "159796.SZ": False,  # 电池
            "561980.SH": False,  # 半导体设备
            "501099.SH": False,  # 平安新兴产业 LOF(混合型,非 QDII)
        }
        for code, t0 in expect_t0.items():
            inst = resolve_instrument(code)
            assert inst.kind == KIND_ETF, code
            assert inst.known is True, code
            assert inst.t0 is t0, code
            assert inst.index_name, code

    def test_user_etf_holdings_are_covered(self):
        """用户实际持有的 ETF 必须能被识别(2026-10-25 券商截图导入的 6 只)

        漏一只 → 徽章退化成「表外虚线灰」,品种属性与 T+0 规则全丢。
        """
        holdings = {
            "159599.SZ": ("芯片ETF东财", "中证芯片产业", False),
            "159732.SZ": ("消费电子ETF华夏", "国证消费电子主题", False),
            "501099.SH": ("平安新兴产业LOF", "中国战略新兴产业", False),
            "561980.SH": ("半导体设备ETF招商", "中证半导体产业", False),
            "562820.SH": ("集成电路ETF嘉实", "中证全指集成电路", False),
            "588160.SH": ("科创新材料ETF南方", "科创新材料", False),
        }
        for code, (name, index, t0) in holdings.items():
            inst = resolve_instrument(code)
            assert inst.kind == KIND_ETF, code
            assert inst.known is True, f"{code} 未收录 → 徽章会退化成表外灰"
            assert inst.display_name == name, code
            assert inst.index_name == index, code
            assert inst.t0 is t0, code
        # 501099 是场内 LOF —— 规则同 ETF,但文案不能说成 ETF
        assert resolve_instrument("501099.SH").is_lof is True


class TestFrontendTableConsistency:
    """前端持有一份品种表副本(徽章要出现在自选/持仓列表,那些接口不返回品种属性)。

    副本由后端表生成,但生成是**一次性脚本** —— 表改了忘记重生成,前后端就会漂移。
    这里逐项比对,把漂移挡在测试里。
    """

    FRONTEND_TABLE = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "lib"
        / "etfInstruments.json"
    )

    def _frontend_items(self) -> dict:
        if not self.FRONTEND_TABLE.exists():
            pytest.skip(f"前端品种表副本不存在: {self.FRONTEND_TABLE}")
        data = json.loads(self.FRONTEND_TABLE.read_text(encoding="utf-8"))
        return {it["code"]: it for it in data["items"]}

    def test_frontend_copy_has_same_code_set(self):
        backend = {i["code"] for i in _backend_items()}
        frontend = set(self._frontend_items())
        assert backend == frontend, (
            f"前后端品种表代码集不一致,缺: {sorted(backend - frontend)}, "
            f"多: {sorted(frontend - backend)}"
        )

    def test_frontend_copy_fields_match(self):
        frontend = self._frontend_items()
        for item in _backend_items():
            fe = frontend[item["code"]]
            for field in ("name", "index", "category", "t0"):
                assert fe.get(field) == item.get(field), (
                    f"{item['code']} 的 {field} 不一致: "
                    f"后端={item.get(field)!r} 前端={fe.get(field)!r}"
                )
            # form 可缺省(= etf),比较时归一
            assert (fe.get("form") or "etf") == (item.get("form") or "etf"), (
                f"{item['code']} 的 form 不一致: "
                f"后端={item.get('form')!r} 前端={fe.get('form')!r}"
            )

    def test_frontend_copy_categories_match(self):
        data = json.loads(self.FRONTEND_TABLE.read_text(encoding="utf-8"))
        backend_map = _backend_categories()
        assert data["categories"] == backend_map


class TestTableDegradation:
    def test_missing_table_does_not_raise(self, monkeypatch, tmp_path):
        """品种表缺失 → 不抛错,走保守路径 + 降级说明"""
        import app.core.instrument as instrument_mod

        monkeypatch.setattr(
            instrument_mod, "_INSTRUMENTS_PATH", tmp_path / "not_exist.json"
        )
        instrument_mod._load_table.cache_clear()
        try:
            inst = instrument_mod.resolve_instrument("513100.SH")
            # 仍按代码格式判定为 ETF,但不能判 T+0(表没了没依据)
            assert inst.kind == KIND_ETF
            assert inst.known is False
            assert inst.t0 is False
            assert instrument_mod.degraded_note("513100.SH") == UNKNOWN_ETF_NOTE
            # 股票判定不受影响
            assert instrument_mod.resolve_instrument("600519.SH").kind == KIND_STOCK
        finally:
            instrument_mod._load_table.cache_clear()

    def test_broken_table_does_not_raise(self, monkeypatch, tmp_path):
        """品种表损坏 → 降级为空表,不抛错"""
        import app.core.instrument as instrument_mod

        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(instrument_mod, "_INSTRUMENTS_PATH", bad)
        instrument_mod._load_table.cache_clear()
        try:
            inst = instrument_mod.resolve_instrument("510300.SH")
            assert inst.kind == KIND_ETF
            assert inst.known is False
        finally:
            instrument_mod._load_table.cache_clear()

    def test_missing_t0_field_defaults_to_false(self, monkeypatch, tmp_path):
        """表项缺 t0 → 按 false(保守),不默认 T+0"""
        import app.core.instrument as instrument_mod

        table = tmp_path / "t.json"
        table.write_text(
            '{"items": [{"code": "510300.SH", "index": "沪深 300", '
            '"category": "broad"}]}',
            encoding="utf-8",
        )
        monkeypatch.setattr(instrument_mod, "_INSTRUMENTS_PATH", table)
        instrument_mod._load_table.cache_clear()
        try:
            inst = instrument_mod.resolve_instrument("510300.SH")
            assert inst.known is True
            assert inst.t0 is False
        finally:
            instrument_mod._load_table.cache_clear()
