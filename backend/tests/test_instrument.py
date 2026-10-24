"""标的品种识别测试(场内 ETF / 股票)

**为什么单独建文件**:品种判定是 ETF 全部交易规则的入口 ——
判错 `kind` 会让费用、T+0 提示、做 T 上限一起错。
所以这里锁住三件事:
1. 表内命中 / 表外格式判定 / 股票不误判
2. 表外 ETF **保守按 T+1**(无据不判 T+0 —— 513100 与 510300 前缀分不开)
3. 表缺失时降级而不抛错
"""
from decimal import Decimal

from app.core.cost_engine import TradeFees
from app.core.instrument import (
    KIND_ETF,
    KIND_STOCK,
    UNKNOWN_ETF_NOTE,
    degraded_note,
    fees_for_instrument,
    resolve_instrument,
)


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
