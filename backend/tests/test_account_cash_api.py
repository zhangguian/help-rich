"""账户可用资金 API 契约测试(/api/accounts/{id}/cash)

覆盖:
- GET  未填写 → cash_available = null(不是 0)
- PUT  写入 → 能读回(量化到 2 位)
- PUT  null → 清空(= 未填写)
- PUT  负数 → 422
- PUT  账户不存在 → 404
- 幂等:重复 PUT 同一值结果一致

**为什么单独建文件**:账户资金是「正T 股数测算」的唯一资金来源,
它的 null 语义(未填写 ≠ 0)直接决定判定层给不给数字 —— 必须单独锁住。
"""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ACCOUNT_ID = 1


def _patch_cash(value: Decimal | None):
    """打桩仓储层 —— 不落库"""
    return patch(
        "app.modules.portfolio.account_repository.account_repo.get_cash_available",
        AsyncMock(return_value=value),
    )


def _patch_set_cash():
    """打桩写入仓储层 —— 不落库"""
    return patch(
        "app.modules.portfolio.account_repository.account_repo.set_cash_available",
        AsyncMock(return_value=True),
    )


def test_get_cash_returns_null_when_unset():
    with _patch_cash(None):
        r = client.get(f"/api/accounts/{ACCOUNT_ID}/cash")
    assert r.status_code == 200
    body = r.json()
    assert body["account_id"] == ACCOUNT_ID
    # 未填写 = null,不是 0 —— 这两个语义对用户完全不同
    assert body["cash_available"] is None


def test_get_cash_returns_saved_value():
    with _patch_cash(Decimal("12345.67")):
        r = client.get(f"/api/accounts/{ACCOUNT_ID}/cash")
    assert r.status_code == 200
    assert float(r.json()["cash_available"]) == 12345.67


def test_put_cash_saves_value():
    with _patch_set_cash(), _patch_cash(Decimal("50000.00")):
        r = client.put(
            f"/api/accounts/{ACCOUNT_ID}/cash", json={"cash_available": "50000"}
        )
    assert r.status_code == 200
    assert float(r.json()["cash_available"]) == 50000.0


def test_put_cash_null_clears():
    """传 null = 清空(= 未填写)"""
    with _patch_set_cash(), _patch_cash(None):
        r = client.put(f"/api/accounts/{ACCOUNT_ID}/cash", json={"cash_available": None})
    assert r.status_code == 200
    assert r.json()["cash_available"] is None


def test_put_cash_negative_rejected():
    with _patch_set_cash():
        r = client.put(
            f"/api/accounts/{ACCOUNT_ID}/cash", json={"cash_available": "-100"}
        )
    assert r.status_code == 422


def test_put_cash_account_not_found_returns_404():
    with patch(
        "app.modules.portfolio.account_repository.account_repo.set_cash_available",
        AsyncMock(return_value=False),
    ):
        r = client.put("/api/accounts/999/cash", json={"cash_available": "100"})
    assert r.status_code == 404
