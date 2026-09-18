"""飞书插件页面：分区、缺配置提示、日期匹配。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "lark-stock"
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from lark_stock.config import LarkConfig  # noqa: E402
from lark_stock.errors import LarkApiError  # noqa: E402
from lark_stock.fields import format_cell, shanghai_midnight_ms, value_matches_day  # noqa: E402
from lark_stock.page import (  # noqa: E402
    bitable_gaps,
    handle_send,
    handle_today,
    im_gaps,
    record_rows,
    render_home,
)


def _config(**kwargs) -> LarkConfig:
    base = dict(
        app_id="cli",
        app_secret="secret",
        domain="feishu",
        drive_folder_token="",
        bitable_app_token="",
        bitable_table_id="",
        duanxian_bitable_app_token="",
        duanxian_bitable_table_id="",
        duanxian_columns={"DUANXIAN_DATE_BITABLE_KEY_NAME": "日期"},
        spreadsheet_token="",
        sheet_id="",
        im_receive_id_type="chat_id",
        im_receive_id="",
    )
    base.update(kwargs)
    return LarkConfig(**base)


def test_home_prompts_missing_config_in_each_section():
    html = render_home(_config(), "abc123")
    assert html.count("<section>") == 2
    assert "今日短线" in html
    assert "发送消息" in html
    assert "多维表格 app_token" in html
    assert "多维表格 table_id" in html
    assert "消息接收方 ID" in html
    assert 'target="_blank"' in html
    assert "/settings/plugins?plugin=abc123&amp;config=1" in html
    assert "拉取今日短线" not in html
    assert "<textarea" not in html


def test_home_shows_actions_when_configured():
    html = render_home(_config(
        bitable_app_token="app",
        bitable_table_id="tbl",
        im_receive_id="oc_1",
    ), "abc123")
    assert "拉取今日短线" in html
    assert "<textarea" in html
    assert "请先配置" not in html
    assert "去配置" not in html


def test_today_refuses_without_bitable():
    called = {"n": 0}

    class Bitable:
        def find_by_date(self, field_name, day):
            called["n"] += 1
            return []

    out = handle_today(SimpleNamespace(config=_config(), bitable=Bitable()), "pid")
    assert out["need_config"] is True
    assert called["n"] == 0
    assert out["config_url"].endswith("plugin=pid&config=1")


def test_record_rows_follow_short_board_order():
    config = _config(duanxian_columns={
        "DUANXIAN_DATE_BITABLE_KEY_NAME": "日期",
        "DUANXIAN_TEMPERATURE_BITABLE_KEY_NAME": "情绪温度",
    })
    rows = record_rows({"备注": "x", "情绪温度": 72, "日期": "2026-09-18"}, config)
    assert [row["label"] for row in rows[:2]] == ["日期", "情绪温度"]
    assert rows[-1]["label"] == "备注"


def test_value_matches_day_text_and_timestamp():
    day = "2026-09-18"
    assert value_matches_day("2026-09-18", day)
    assert value_matches_day("2026/9/18", day)
    assert value_matches_day([{"text": "2026年9月18日"}], day)
    assert value_matches_day(shanghai_midnight_ms(day), day)
    assert not value_matches_day("2026-09-17", day)
    assert format_cell([{"text": "龙头"}]) == "龙头"


def test_find_by_date_uses_exact_date_for_date_column():
    from lark_stock.bitable import BitableStore

    seen: list[list[str]] = []

    class Field:
        field_name = "日期"
        type = 5
        ui_type = "DateTime"

    class Data:
        def __init__(self, items=None, has_more=False):
            self.items = items or []
            self.has_more = has_more
            self.page_token = None

    class Resp:
        def __init__(self, data):
            self.data = data

        def success(self):
            return True

    class FieldApi:
        def list(self, request):
            return Resp(Data([Field()]))

    class RecordApi:
        def search(self, request):
            seen.append(list(request.request_body.filter.conditions[0].value))
            return Resp(Data())

        def list(self, request):
            raise AssertionError("日期列不应再整表扫描")

    class V1:
        app_table_field = FieldApi()
        app_table_record = RecordApi()

    class BitableApi:
        v1 = V1()

    class Client:
        bitable = BitableApi()

    store = BitableStore(Client(), _config(bitable_app_token="app", bitable_table_id="tbl"))
    assert store.find_by_date("日期", "2026-09-18") == []
    assert seen == [["ExactDate", str(shanghai_midnight_ms("2026-09-18"))]]


def test_find_by_date_scans_when_text_search_fails():
    from lark_stock.bitable import BitableStore

    class Field:
        field_name = "日期"
        type = 1
        ui_type = "Text"

    class Record:
        def __init__(self, record_id, fields):
            self.record_id = record_id
            self.fields = fields

    class Data:
        def __init__(self, items=None, has_more=False):
            self.items = items or []
            self.has_more = has_more
            self.page_token = None

    class Resp:
        def __init__(self, data):
            self.data = data

        def success(self):
            return True

    class FieldApi:
        def list(self, request):
            return Resp(Data([Field()]))

    class RecordApi:
        def search(self, request):
            raise LarkApiError("检索多维表格记录", 1254018, "类型不匹配")

        def list(self, request):
            return Resp(Data([
                Record("rec1", {"日期": "2026/9/18", "情绪温度": 60}),
                Record("rec2", {"日期": "2026-09-17"}),
            ]))

    class V1:
        app_table_field = FieldApi()
        app_table_record = RecordApi()

    class BitableApi:
        v1 = V1()

    class Client:
        bitable = BitableApi()

    store = BitableStore(Client(), _config(bitable_app_token="app", bitable_table_id="tbl"))
    rows = store.find_by_date("日期", "2026-09-18")
    assert [row["record_id"] for row in rows] == ["rec1"]


def test_send_requires_text():
    class Request:
        _body = b'{"text":"  "}'

    out = handle_send(
        SimpleNamespace(config=_config(im_receive_id="oc_1"), messenger=None),
        Request(),
        "pid",
    )
    assert out["ok"] is False
    assert "请输入" in out["error"]
    assert im_gaps(_config()) and not bitable_gaps(_config(
        bitable_app_token="a",
        bitable_table_id="b",
    ))
