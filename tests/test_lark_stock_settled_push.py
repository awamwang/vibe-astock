"""收盘后自动推送定稿短线：探测条件、每日一次、群通知。"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "lark-stock"
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from lark_stock.config import LarkConfig  # noqa: E402
from lark_stock.settled_push import (  # noqa: E402
    SETTLED_NOTICE,
    SettledPushPoller,
    last_push_at,
    payload_all_settled,
    record_push_success,
)


def _config(**kwargs) -> LarkConfig:
    base = dict(
        app_id="cli",
        app_secret="secret",
        domain="feishu",
        drive_folder_token="",
        bitable_app_token="app",
        bitable_table_id="tbl",
        duanxian_bitable_app_token="app",
        duanxian_bitable_table_id="tbl",
        duanxian_columns={"DUANXIAN_DATE_BITABLE_KEY_NAME": "日期"},
        spreadsheet_token="",
        sheet_id="",
        im_receive_id_type="chat_id",
        im_receive_id="oc_1",
    )
    base.update(kwargs)
    return LarkConfig(**base)


def _source(settled=True, available=True, date="2026-09-18", **extra):
    data = {"settled": settled, "date": date, **extra}
    return {"available": available, "data": data}


def _payload(*, date="2026-09-18", board=True, emotion=True, zt=True):
    return {
        "date": date,
        "sources": {
            "short_board": _source(settled=board, date=date, today={"temperature": 72}),
            "live_emotion": _source(settled=emotion, date=date, max_boards=5),
            "live_zt_effect": _source(settled=zt, date=date, open_success_rate=0.5),
        },
    }


def test_payload_all_settled_requires_three_sources():
    today = "2026-09-18"
    assert payload_all_settled(_payload(), today)
    assert not payload_all_settled(_payload(board=False), today)
    assert not payload_all_settled(_payload(emotion=False), today)
    assert not payload_all_settled(_payload(zt=False), today)
    assert not payload_all_settled(_payload(date="2026-09-17"), today)
    missing = _payload()
    missing["sources"]["short_board"] = {"available": False, "data": None}
    assert not payload_all_settled(missing, today)


@pytest.fixture(autouse=True)
def _reset_active_poller():
    import lark_stock.settled_push as sp

    prev = sp._ACTIVE
    sp._ACTIVE = None
    yield
    sp._ACTIVE = prev


def _poller(tmp_path, *, fetch_live, store=None, messenger=None, config=None, interval=30.0):
    sent = []
    written = []

    class Store:
        def upsert_by_date(self, field_name, day, fields):
            written.append({"field": field_name, "day": day, "fields": dict(fields)})
            return {"action": "create", "record_id": "rec1", "matched": 0}

    class Messenger:
        def send_text(self, text):
            sent.append(text)
            return "mid-1"

    service = SimpleNamespace(
        config=config or _config(),
        duanxian_bitable=store or Store(),
        messenger=messenger or Messenger(),
    )
    poller = SettledPushPoller(
        service=service,
        plugin_id="pid",
        fetch_live=fetch_live,
        state_path=tmp_path / "state.json",
        interval=interval,
    )
    return poller, sent, written


@pytest.mark.unit
def test_tick_skips_before_close(monkeypatch, tmp_path):
    monkeypatch.setattr("lark_stock.settled_push.china_today", lambda: "2026-09-18")
    monkeypatch.setattr("lark_stock.settled_push.is_settled", lambda d: False)
    called = {"n": 0}

    poller, sent, written = _poller(tmp_path, fetch_live=lambda: called.__setitem__("n", 1) or _payload())
    assert poller.tick() == "skip_window"
    assert called["n"] == 0
    assert sent == []
    assert written == []


@pytest.mark.unit
def test_tick_waits_until_all_sources_settled(monkeypatch, tmp_path):
    monkeypatch.setattr("lark_stock.settled_push.china_today", lambda: "2026-09-18")
    monkeypatch.setattr("lark_stock.settled_push.is_settled", lambda d: d == "2026-09-18")
    poller, sent, written = _poller(tmp_path, fetch_live=lambda: _payload(zt=False))
    assert poller.tick() == "wait_settle"
    assert sent == []
    assert written == []


@pytest.mark.unit
def test_tick_pushes_once_then_notifies(monkeypatch, tmp_path):
    monkeypatch.setattr("lark_stock.settled_push.china_today", lambda: "2026-09-18")
    monkeypatch.setattr("lark_stock.settled_push.is_settled", lambda d: True)
    fetches = {"n": 0}

    def fetch():
        fetches["n"] += 1
        return _payload()

    poller, sent, written = _poller(tmp_path, fetch_live=fetch)
    monkeypatch.setattr("lark_stock.settled_push.now_pushed_at", lambda: "2026-09-18 15:32:10")
    assert poller.tick() == "pushed"
    assert [row["day"] for row in written] == ["2026-09-18"]
    assert sent == [SETTLED_NOTICE]
    assert poller.last_pushed_at() == "2026-09-18 15:32:10"
    assert poller.tick() == "skip_done"
    assert fetches["n"] == 1
    assert len(written) == 1
    assert sent == [SETTLED_NOTICE]


@pytest.mark.unit
def test_tick_does_not_notify_if_push_fails(monkeypatch, tmp_path):
    monkeypatch.setattr("lark_stock.settled_push.china_today", lambda: "2026-09-18")
    monkeypatch.setattr("lark_stock.settled_push.is_settled", lambda d: True)

    class Store:
        def upsert_by_date(self, field_name, day, fields):
            raise RuntimeError("飞书不可用")

    poller, sent, _written = _poller(tmp_path, fetch_live=_payload, store=Store())
    assert poller.tick() == "push_error"
    assert sent == []
    assert poller.tick() == "push_error"


@pytest.mark.unit
def test_tick_retries_notify_without_repushing(monkeypatch, tmp_path):
    monkeypatch.setattr("lark_stock.settled_push.china_today", lambda: "2026-09-18")
    monkeypatch.setattr("lark_stock.settled_push.is_settled", lambda d: True)
    attempts = {"n": 0}

    class Messenger:
        def send_text(self, text):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("im down")
            return "mid-2"

    poller, _sent, written = _poller(tmp_path, fetch_live=_payload, messenger=Messenger())
    assert poller.tick() == "notify_error"
    assert len(written) == 1
    assert poller.tick() == "pushed"
    assert len(written) == 1
    assert attempts["n"] == 2


@pytest.mark.unit
def test_tick_persists_once_per_day_across_instances(monkeypatch, tmp_path):
    monkeypatch.setattr("lark_stock.settled_push.china_today", lambda: "2026-09-18")
    monkeypatch.setattr("lark_stock.settled_push.is_settled", lambda d: True)
    first, sent, written = _poller(tmp_path, fetch_live=_payload)
    monkeypatch.setattr("lark_stock.settled_push.now_pushed_at", lambda: "2026-09-18 15:32:10")
    assert first.tick() == "pushed"
    assert first.last_pushed_at() == "2026-09-18 15:32:10"
    second, sent2, written2 = _poller(tmp_path, fetch_live=_payload)
    assert second.tick() == "skip_done"
    assert second.last_pushed_at() == "2026-09-18 15:32:10"
    assert sent == [SETTLED_NOTICE]
    assert sent2 == []
    assert written2 == []


@pytest.mark.unit
def test_record_push_success_updates_active_poller_time(monkeypatch, tmp_path):
    monkeypatch.setattr("lark_stock.settled_push.china_today", lambda: "2026-09-18")
    monkeypatch.setattr("lark_stock.settled_push.is_settled", lambda d: False)
    poller, _sent, _written = _poller(tmp_path, fetch_live=_payload)
    poller.start()
    try:
        assert last_push_at() == ""
        assert record_push_success("2026-09-18 16:01:02") == "2026-09-18 16:01:02"
        assert last_push_at() == "2026-09-18 16:01:02"
        assert poller.last_pushed_at() == "2026-09-18 16:01:02"
    finally:
        poller.stop()


@pytest.mark.unit
def test_poller_stop_unblocks_wait(monkeypatch, tmp_path):
    monkeypatch.setattr("lark_stock.settled_push.china_today", lambda: "2026-09-18")
    monkeypatch.setattr("lark_stock.settled_push.is_settled", lambda d: False)
    poller, _sent, _written = _poller(tmp_path, fetch_live=_payload, interval=30.0)
    poller.start()
    started = time.monotonic()
    poller.stop()
    elapsed = time.monotonic() - started
    assert elapsed < 2.0
    thread = poller._thread
    assert thread is None or not thread.is_alive()


@pytest.mark.unit
def test_stop_does_not_deadlock_during_in_flight_push(monkeypatch, tmp_path):
    monkeypatch.setattr("lark_stock.settled_push.china_today", lambda: "2026-09-18")
    monkeypatch.setattr("lark_stock.settled_push.is_settled", lambda d: True)
    entered = threading.Event()
    release = threading.Event()

    class Store:
        def upsert_by_date(self, field_name, day, fields):
            entered.set()
            release.wait(timeout=8.0)
            return {"action": "create", "record_id": "rec1", "matched": 0}

    poller, _sent, _written = _poller(
        tmp_path, fetch_live=_payload, store=Store(), interval=0.05,
    )
    poller.start()
    assert entered.wait(timeout=2.0)
    started = time.monotonic()
    stopper = threading.Thread(target=poller.stop, name="settled-stop", daemon=True)
    stopper.start()
    stopper.join(timeout=6.0)
    assert stopper.is_alive() is False
    assert time.monotonic() - started < 6.0
    release.set()
