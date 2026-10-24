"""Settings 与价格表（Task 1）。"""

from __future__ import annotations

import pytest

from app.config import PRICES, ReaderNotConfigured, Settings

REQUIRED_ENV = (
    "WRITER_API_KEY",
    "WRITER_BASE_URL",
    "WRITER_MODEL",
    "READER_API_KEY",
    "READER_BASE_URL",
    "READER_MODEL",
)


def test_reader_provider_must_be_explicit(monkeypatch):
    """读者配置缺失时必须报错，不允许回落到 writer 的 key（§13：换厂商是机制）。"""
    for name in REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ReaderNotConfigured, match="READER_"):
        Settings.load()


def test_price_table_is_structured():
    """只断言结构：价格会变，写死数值等于让测试明天就红。"""
    assert "deepseek-flash" in PRICES
    assert all(isinstance(v, tuple) and len(v) == 2 for v in PRICES.values())
