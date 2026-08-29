"""账户日快照：命名栏位、格式化摘要、同日覆盖。"""

from __future__ import annotations

import os

import pytest

from duanxian import trade_store as ts


@pytest.fixture()
def account_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    # 模块级路径在 import 时已定；直接改常量
    monkeypatch.setattr(ts, "_ACCOUNT_DIR", str(tmp_path))
    monkeypatch.setattr(ts, "_ACCOUNT_FILE", os.path.join(str(tmp_path), "trade_account.json"))
    return tmp_path


class TestFormatSummary:
    def test_named_format_matches_broker_ui(self):
        s = ts.format_account_summary({
            "account_name": "中金财富-王*",
            "cash_balance": 440.85,
            "account_display": "中金财富6323",
            "broker": "中金财富",
            "available": 3404.15,
            "stock_market_value": 132736,
            "daily_pnl": -4698.75,
            "daily_pnl_pct": -3.34,
        })
        assert s == (
            "账户名中金财富-王*，资金余额440.85，右下角显示中金财富6323"
            "｜来源:中金财富 · 可用3404.15 · 市值132736 · 当日盈亏-4698.75 · 当日盈亏比-3.34%"
        )


class TestSnapshotOverwrite:
    def test_same_day_overwrites_named_fields(self, account_home):
        ts.set_equity(100000, fields={
            "account_name": "中金财富-王*",
            "available": 1000,
            "stock_market_value": 90000,
        })
        d1 = ts.snapshot_equity("2026-08-19", 90000)
        assert d1["snapshots"]["2026-08-19"]["available"] == 1000
        assert "账户名中金财富-王*" in d1["snapshots"]["2026-08-19"]["summary"]

        d2 = ts.snapshot_equity("2026-08-19", 132736, {
            "account_name": "中金财富-王*",
            "cash_balance": 440.85,
            "account_display": "中金财富6323",
            "broker": "中金财富",
            "available": 3404.15,
            "stock_market_value": 132736,
            "daily_pnl": -4698.75,
            "daily_pnl_pct": -3.34,
        })
        snap = d2["snapshots"]["2026-08-19"]
        assert len(d2["snapshots"]) == 1
        assert snap["available"] == 3404.15
        assert snap["cash_balance"] == 440.85
        assert snap["market_value"] == 132736
        assert snap["daily_pnl"] == -4698.75
        assert "右下角显示中金财富6323" in snap["summary"]

        # 另一天独立保留
        ts.snapshot_equity("2026-08-18", 80000, {"available": 500})
        assert "2026-08-18" in ts.load_account()["snapshots"]
        assert ts.load_account()["snapshots"]["2026-08-19"]["available"] == 3404.15


class TestDeleteSnapshot:
    def test_deletes_snapshot_and_day_budget(self, account_home, tmp_path, monkeypatch):
        trade_dir = tmp_path / "trade"
        trade_dir.mkdir()
        monkeypatch.setattr(ts, "_TRADE_DIR", str(trade_dir))

        ts.set_equity(100000, fields={"available": 1000})
        ts.snapshot_equity("2026-08-19", 90000)
        ts.snapshot_equity("2026-08-18", 80000)

        day_path = trade_dir / "2026-08-19.json"
        day_path.write_text(
            '{"schema": 1, "date": "2026-08-19", "phase": "正常"}',
            encoding="utf-8",
        )
        keep_path = trade_dir / "2026-08-18.json"
        keep_path.write_text(
            '{"schema": 1, "date": "2026-08-18", "phase": "正常"}',
            encoding="utf-8",
        )

        result = ts.delete_snapshot("2026-08-19")
        assert result["removed_snapshot"] is True
        assert result["removed_budget"] is True
        assert "2026-08-19" not in result["account"]["snapshots"]
        assert "2026-08-18" in result["account"]["snapshots"]
        assert not day_path.exists()
        assert keep_path.exists()

    def test_delete_missing_is_noop_flags(self, account_home, tmp_path, monkeypatch):
        monkeypatch.setattr(ts, "_TRADE_DIR", str(tmp_path / "trade"))
        result = ts.delete_snapshot("2026-01-01")
        assert result["removed_snapshot"] is False
        assert result["removed_budget"] is False
