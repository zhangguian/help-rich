"""ScreenerPick.fundamental_filter_status 列测试 (改动 B)"""
import pytest
from app.models.orm import ScreenerPick
from sqlalchemy import inspect


def test_screener_pick_has_fundamental_filter_status_column():
    """验证 ORM 模型有 fundamental_filter_status 列"""
    cols = {c.name for c in ScreenerPick.__table__.columns}
    assert "fundamental_filter_status" in cols