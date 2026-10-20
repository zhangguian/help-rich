"""价格提醒条件引擎单测(纯函数,无 IO)。"""
import pytest

from app.modules.alert.engine import (
    AlertConditionError,
    AlertContext,
    describe,
    evaluate,
    fingerprint,
    validate,
)


class TestLeafConditions:
    def test_price_greater_than(self):
        node = {"metric": "price", "op": ">", "value": 10}
        assert evaluate(node, AlertContext(price=11.0)) is True
        assert evaluate(node, AlertContext(price=9.0)) is False

    @pytest.mark.parametrize(
        "op,value,actual,expected",
        [
            (">=", 10, 10, True),
            ("<=", 10, 10, True),
            ("<", 10, 10, False),
            ("==", 10, 10, True),
            ("!=", 10, 11, True),
        ],
    )
    def test_comparators(self, op, value, actual, expected):
        node = {"metric": "price", "op": op, "value": value}
        assert evaluate(node, AlertContext(price=actual)) is expected

    def test_missing_metric_is_false(self):
        """行情快照缺该指标时判 False,而不是抛错。"""
        node = {"metric": "volume_ratio", "op": ">", "value": 2}
        assert evaluate(node, AlertContext(price=10.0)) is False

    def test_unknown_metric_is_false(self):
        node = {"metric": "不存在", "op": ">", "value": 1}
        assert evaluate(node, AlertContext(price=10.0)) is False

    def test_unknown_op_is_false(self):
        node = {"metric": "price", "op": "≈", "value": 1}
        assert evaluate(node, AlertContext(price=10.0)) is False


class TestCompositeConditions:
    def test_and_requires_all(self):
        node = {
            "op": "and",
            "conditions": [
                {"metric": "price", "op": "<=", "value": 12.5},
                {"metric": "volume_ratio", "op": ">", "value": 2.0},
            ],
        }
        assert evaluate(node, AlertContext(price=12.0, volume_ratio=2.5)) is True
        assert evaluate(node, AlertContext(price=12.0, volume_ratio=1.0)) is False
        assert evaluate(node, AlertContext(price=13.0, volume_ratio=2.5)) is False

    def test_or_requires_any(self):
        node = {
            "op": "or",
            "conditions": [
                {"metric": "price", "op": "<=", "value": 12.0},
                {"metric": "change_pct", "op": ">=", "value": 5.0},
            ],
        }
        assert evaluate(node, AlertContext(price=11.0)) is True
        assert evaluate(node, AlertContext(price=20.0, change_pct=6.0)) is True
        assert evaluate(node, AlertContext(price=20.0, change_pct=1.0)) is False

    def test_nested_and_or(self):
        node = {
            "op": "and",
            "conditions": [
                {"metric": "price", "op": "<=", "value": 12.0},
                {
                    "op": "or",
                    "conditions": [
                        {"metric": "volume_ratio", "op": ">", "value": 2.0},
                        {"metric": "turnover", "op": ">", "value": 8.0},
                    ],
                },
            ],
        }
        assert evaluate(node, AlertContext(price=11.0, volume_ratio=3.0)) is True
        assert evaluate(node, AlertContext(price=11.0, turnover=9.0)) is True
        assert evaluate(node, AlertContext(price=11.0, turnover=1.0)) is False

    def test_empty_conditions_is_false(self):
        """空条件树不视为恒真,避免无规则时误推送。"""
        assert evaluate(None, AlertContext(price=10)) is False
        assert evaluate({}, AlertContext(price=10)) is False
        assert evaluate({"op": "and", "conditions": []}, AlertContext(price=10)) is False


class TestFingerprint:
    def test_same_bucket_same_fingerprint(self):
        node = {"metric": "price", "op": "<=", "value": 12}
        a = fingerprint(node, AlertContext(price=10.01))
        b = fingerprint(node, AlertContext(price=10.02))
        assert a == b

    def test_different_bucket_different_fingerprint(self):
        node = {"metric": "price", "op": "<=", "value": 12}
        a = fingerprint(node, AlertContext(price=10.0))
        b = fingerprint(node, AlertContext(price=9.0))
        assert a != b

    def test_different_conditions_different_fingerprint(self):
        ctx = AlertContext(price=10.0)
        a = fingerprint({"metric": "price", "op": "<=", "value": 12}, ctx)
        b = fingerprint({"metric": "price", "op": "<=", "value": 13}, ctx)
        assert a != b


class TestValidate:
    def test_valid_tree_passes(self):
        validate(
            {
                "op": "and",
                "conditions": [
                    {"metric": "price", "op": "<=", "value": 12.5},
                    {"metric": "volume_ratio", "op": ">", "value": 2},
                ],
            }
        )

    @pytest.mark.parametrize(
        "node",
        [
            None,
            {},
            {"metric": "不存在", "op": ">", "value": 1},
            {"metric": "price", "op": "≈", "value": 1},
            {"metric": "price", "op": ">", "value": "abc"},
            {"op": "xor", "conditions": [{"metric": "price", "op": ">", "value": 1}]},
            {"op": "and", "conditions": []},
            {"op": "and"},
        ],
    )
    def test_invalid_tree_raises(self, node):
        with pytest.raises(AlertConditionError):
            validate(node)

    def test_depth_limit(self):
        node = {"metric": "price", "op": ">", "value": 1}
        for _ in range(5):
            node = {"op": "and", "conditions": [node]}
        with pytest.raises(AlertConditionError, match="嵌套过深"):
            validate(node)


class TestDescribe:
    def test_describe_leaf_and_group(self):
        assert describe({"metric": "price", "op": "<=", "value": 12.5}) == "价格 <= 12.5"
        text = describe(
            {
                "op": "and",
                "conditions": [
                    {"metric": "price", "op": "<=", "value": 12.5},
                    {"metric": "volume_ratio", "op": ">", "value": 2},
                ],
            }
        )
        assert "价格" in text and "量比" in text and "且" in text
