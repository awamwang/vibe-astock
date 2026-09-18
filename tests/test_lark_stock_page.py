"""飞书插件页面：分区、缺配置提示、日期匹配。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "lark-stock"
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from lark_stock.config import LarkConfig  # noqa: E402
from lark_stock.errors import LarkApiError  # noqa: E402
from lark_stock.fields import format_cell, shanghai_midnight_ms, value_matches_day  # noqa: E402
from lark_stock.page import (  # noqa: E402
    bitable_gaps,
    handle_push,
    handle_send,
    handle_today,
    im_gaps,
    push_gaps,
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
    assert "推送今日短线盘面" not in html
    assert "<textarea" not in html


def test_home_shows_actions_when_configured():
    html = render_home(_config(
        bitable_app_token="app",
        bitable_table_id="tbl",
        im_receive_id="oc_1",
    ), "abc123")
    assert "拉取今日短线" in html
    assert "推送今日短线盘面" in html
    assert "data.hint" in html
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
    assert not push_gaps(_config(bitable_app_token="a", bitable_table_id="b"))
    assert push_gaps(_config())


def test_extract_duanxian_values_use_env_column_names():
    from lark_stock.duanxian_row import extract_duanxian_values, to_bitable_fields

    payload = {
        "date": "2026-09-18",
        "sources": {
            "short_board": {
                "available": True,
                "data": {
                    "today": {
                        "temperature": 72,
                        "v_sh": 5.2e11,
                        "qcj_temp": 55,
                        "qcj_level": "升温期",
                        "qcj_leader": "某龙头",
                        "qcj_leader_top": "3天3板",
                        "qcj_themes": ["人工智能", "芯片"],
                        "broken_r": 18.5,
                    }
                },
            },
            "live_emotion": {
                "available": True,
                "data": {"max_boards": 5, "promotion_rate": 0.4, "lianban_count": 12, "zb_count": 30},
            },
            "live_zt_effect": {
                "available": True,
                "data": {"open_success_rate": 0.62, "consec_premium_avg": 3.2, "deep_loss_5_count": 7},
            },
            "market_sentiment": {
                "available": True,
                "data": {"breadth": "偏强", "speculation": "活跃", "up": 3200, "down": 1800, "flat": 200, "active": "62%"},
            },
            "board_emotion_resonance": {
                "available": True,
                "data": {"default": {"score": 0.123, "label": "偏多"}},
            },
        },
    }
    values = extract_duanxian_values(payload, date="2026-09-18")
    assert values["DUANXIAN_TEMPERATURE_BITABLE_KEY_NAME"] == 72
    assert values["DUANXIAN_SH_VOLUME_BITABLE_KEY_NAME"] == 5200.0
    assert values["DUANXIAN_PROMOTION_BITABLE_KEY_NAME"] == 40.0
    assert values["DUANXIAN_LEADER_BITABLE_KEY_NAME"] == "某龙头 · 3天3板"
    assert values["DUANXIAN_RESONANCE_BITABLE_KEY_NAME"] == "0.123 偏多"
    fields = to_bitable_fields(values, {
        "DUANXIAN_DATE_BITABLE_KEY_NAME": "交易日",
        "DUANXIAN_TEMPERATURE_BITABLE_KEY_NAME": "温度",
        "DUANXIAN_BREADTH_BITABLE_KEY_NAME": "宽度",
    })
    assert fields["交易日"] == "2026-09-18"
    assert fields["温度"] == 72
    assert fields["宽度"] == "偏强"
    assert "情绪温度" not in fields


def test_push_refuses_without_table():
    out = handle_push(SimpleNamespace(config=_config(), duanxian_bitable=None), "pid")
    assert out["need_config"] is True
    assert "短线盘面" in out["error"] or "日期列名" in out["error"]


def test_push_creates_then_updates_by_date():
    written: list[dict] = []

    class Store:
        def upsert_by_date(self, field_name, day, fields):
            written.append({"field": field_name, "day": day, "fields": dict(fields)})
            action = "create" if len(written) == 1 else "update"
            return {"action": action, "record_id": "rec1", "matched": 0 if action == "create" else 1}

    payload = {
        "date": "2026-09-18",
        "sources": {
            "short_board": {"available": True, "data": {"today": {"temperature": 80}}},
        },
    }
    service = SimpleNamespace(
        config=_config(
            duanxian_bitable_app_token="app",
            duanxian_bitable_table_id="tbl",
            duanxian_columns={
                "DUANXIAN_DATE_BITABLE_KEY_NAME": "交易日",
                "DUANXIAN_TEMPERATURE_BITABLE_KEY_NAME": "温度",
            },
        ),
        duanxian_bitable=Store(),
    )
    created = handle_push(service, "pid", fetch_live=lambda: payload)
    updated = handle_push(service, "pid", fetch_live=lambda: payload)
    assert created["ok"] is True and created["action"] == "create"
    assert updated["ok"] is True and updated["action"] == "update"
    assert written[0]["field"] == "交易日"
    assert written[0]["fields"]["交易日"] == "2026-09-18"
    assert written[0]["fields"]["温度"] == 80


def test_push_surfaces_skipped_column_hint():
    class Store:
        def upsert_by_date(self, field_name, day, fields):
            return {
                "action": "create",
                "record_id": "rec1",
                "matched": 0,
                "fields": {"交易日": day},
                "skipped": ["温度"],
                "hint": "已跳过表里没有的列：「温度」。请把插件配置里的列名改成与表格完全一致（含空格和符号）。",
            }

    payload = {
        "date": "2026-09-18",
        "sources": {
            "short_board": {"available": True, "data": {"today": {"temperature": 80}}},
        },
    }
    out = handle_push(
        SimpleNamespace(
            config=_config(
                duanxian_bitable_app_token="app",
                duanxian_bitable_table_id="tbl",
                duanxian_columns={
                    "DUANXIAN_DATE_BITABLE_KEY_NAME": "交易日",
                    "DUANXIAN_TEMPERATURE_BITABLE_KEY_NAME": "温度",
                },
            ),
            duanxian_bitable=Store(),
        ),
        "pid",
        fetch_live=lambda: payload,
    )
    assert out["ok"] is True
    assert "温度" in out["hint"]
    assert out["skipped"] == ["温度"]
    assert [row["label"] for row in out["rows"]] == ["日期"]


def test_upsert_by_date_updates_existing_date_row():
    from lark_stock.bitable import BitableStore

    class Field:
        field_name = "日期"
        type = 5
        ui_type = "DateTime"

    class Temp:
        field_name = "情绪温度"
        type = 2
        ui_type = "Number"

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
        def __init__(self, data=None, record=None):
            self.data = data
            self.record = record

        def success(self):
            return True

    updated: list[tuple[str, dict]] = []
    created: list[dict] = []

    class FieldApi:
        def list(self, request):
            return Resp(Data([Field(), Temp()]))

    class RecordApi:
        def search(self, request):
            return Resp(Data([Record("rec-old", {"日期": shanghai_midnight_ms("2026-09-18")})]))

        def update(self, request):
            updated.append((request.record_id, request.request_body.fields))
            return Resp()

        def create(self, request):
            created.append(request.request_body.fields)
            rec = SimpleNamespace(record_id="rec-new")
            return Resp(SimpleNamespace(record=rec))

        def list(self, request):
            raise AssertionError("不应整表扫描")

    class V1:
        app_table_field = FieldApi()
        app_table_record = RecordApi()

    class Client:
        bitable = SimpleNamespace(v1=V1())

    store = BitableStore(Client(), _config(bitable_app_token="app", bitable_table_id="tbl"))
    out = store.upsert_by_date("日期", "2026-09-18", {"情绪温度": 66})
    assert out["action"] == "update"
    assert out["record_id"] == "rec-old"
    assert updated[0][1]["情绪温度"] == 66
    assert updated[0][1]["日期"] == shanghai_midnight_ms("2026-09-18")
    assert created == []


def test_upsert_skips_missing_field_names_and_returns_hint():
    from lark_stock.bitable import BitableStore

    class Field:
        def __init__(self, name, type_, ui):
            self.field_name = name
            self.type = type_
            self.ui_type = ui

    class Data:
        def __init__(self, items=None, has_more=False):
            self.items = items or []
            self.has_more = has_more
            self.page_token = None

    class Resp:
        def __init__(self, data=None):
            self.data = data

        def success(self):
            return True

    created: list[dict] = []

    class FieldApi:
        def list(self, request):
            return Resp(Data([
                Field("日期", 5, "DateTime"),
                Field("炸板个数", 2, "Number"),
            ]))

    class RecordApi:
        def search(self, request):
            return Resp(Data())

        def list(self, request):
            return Resp(Data())

        def create(self, request):
            created.append(request.request_body.fields)
            rec = SimpleNamespace(record_id="rec-new")
            return Resp(SimpleNamespace(record=rec))

    store = BitableStore(
        SimpleNamespace(bitable=SimpleNamespace(v1=SimpleNamespace(
            app_table_field=FieldApi(),
            app_table_record=RecordApi(),
        ))),
        _config(bitable_app_token="app", bitable_table_id="tbl"),
    )
    out = store.upsert_by_date("日期", "2026-09-18", {
        "日期": "2026-09-18",
        "情绪温度": 66,
        "炸板家数": 8,
    })
    assert out["action"] == "create"
    assert created[0]["日期"] == shanghai_midnight_ms("2026-09-18")
    assert "情绪温度" not in created[0]
    assert "炸板家数" not in created[0]
    assert out["skipped"] == ["情绪温度", "炸板家数"]
    assert "已跳过" in out["hint"]
    assert "情绪温度" in out["hint"]
    assert "炸板家数" in out["hint"]
    assert "炸板个数" in out["hint"]


def test_create_record_1254045_lists_written_columns():
    from lark_stock.bitable import BitableStore

    class Data:
        def __init__(self, items=None, has_more=False):
            self.items = items or []
            self.has_more = has_more
            self.page_token = None

    class Fail:
        code = 1254045
        msg = "FieldNameNotFound"
        data = None

        def success(self):
            return False

        def get_log_id(self):
            return "log-field"

    class FieldApi:
        def list(self, request):
            raise LarkApiError("列出多维表格字段", 1254001, "fail")

    class RecordApi:
        def create(self, request):
            return Fail()

    store = BitableStore(
        SimpleNamespace(bitable=SimpleNamespace(v1=SimpleNamespace(
            app_table_field=FieldApi(),
            app_table_record=RecordApi(),
        ))),
        _config(bitable_app_token="app", bitable_table_id="tbl"),
    )
    with pytest.raises(LarkApiError, match="情绪温度") as caught:
        store.create_record({"日期": "2026-09-18", "情绪温度": 66})
    text = str(caught.value)
    assert "1254045" in text
    assert "日期" in text
    assert "本次写入" in text


def test_91403_explains_how_to_grant_edit():
    from lark_stock.errors import LarkApiError

    err = LarkApiError("新增多维表格记录", 91403, "Forbidden", "log-1")
    text = str(err)
    assert "91403" in text
    assert "添加文档应用" in text
    assert "可编辑" in text


def test_1254045_explains_field_name_mismatch():
    err = LarkApiError("新增多维表格记录", 1254045, "FieldNameNotFound", "log-2")
    text = str(err)
    assert "1254045" in text
    assert "列名" in text


def test_1254061_explains_number_conversion():
    err = LarkApiError("新增多维表格记录", 1254061, "NumberFieldConvFail", "log-3")
    text = str(err)
    assert "1254061" in text
    assert "百分比" in text


def test_upsert_skips_formula_columns():
    from lark_stock.bitable import BitableStore

    class Field:
        def __init__(self, name, type_, ui):
            self.field_name = name
            self.type = type_
            self.ui_type = ui

    class Data:
        def __init__(self, items=None, has_more=False):
            self.items = items or []
            self.has_more = has_more
            self.page_token = None

    class Resp:
        def __init__(self, data=None):
            self.data = data

        def success(self):
            return True

    created: list[dict] = []

    class FieldApi:
        def list(self, request):
            return Resp(Data([
                Field("日期", 1, "Text"),
                Field("情绪温度", 2, "Number"),
                Field("公式列", 20, "Formula"),
            ]))

    class RecordApi:
        def search(self, request):
            return Resp(Data())

        def list(self, request):
            return Resp(Data())

        def create(self, request):
            created.append(request.request_body.fields)
            rec = SimpleNamespace(record_id="rec-new")
            return Resp(SimpleNamespace(record=rec))

    store = BitableStore(
        SimpleNamespace(bitable=SimpleNamespace(v1=SimpleNamespace(
            app_table_field=FieldApi(),
            app_table_record=RecordApi(),
        ))),
        _config(bitable_app_token="app", bitable_table_id="tbl"),
    )
    out = store.upsert_by_date("日期", "2026-09-18", {
        "日期": "2026-09-18",
        "情绪温度": 66,
        "公式列": 1,
    })
    assert out["action"] == "create"
    assert "公式列" not in created[0]
    assert created[0]["情绪温度"] == 66


def test_coerce_text_number_percent_values():
    from lark_stock.fields import coerce_bitable_value

    assert coerce_bitable_value(72, "text") == "72"
    assert coerce_bitable_value("12", "number") == 12
    assert coerce_bitable_value("62%", "number") == 62
    assert coerce_bitable_value("0.123 偏多", "number") == 0.123
    assert coerce_bitable_value("偏强", "number") is None
    assert coerce_bitable_value(40, "percent") == 0.4
    assert coerce_bitable_value("62%", "percent") == 0.62
    assert coerce_bitable_value(0.4, "percent") == 0.4


def test_upsert_coerces_text_number_percent_columns():
    from lark_stock.bitable import BitableStore

    class Field:
        def __init__(self, name, type_, ui, formatter=""):
            self.field_name = name
            self.type = type_
            self.ui_type = ui
            self.property = SimpleNamespace(formatter=formatter or None)

    class Data:
        def __init__(self, items=None, has_more=False):
            self.items = items or []
            self.has_more = has_more
            self.page_token = None

    class Resp:
        def __init__(self, data=None):
            self.data = data

        def success(self):
            return True

    created: list[dict] = []

    class FieldApi:
        def list(self, request):
            return Resp(Data([
                Field("日期", 5, "DateTime"),
                Field("备注", 1, "Text"),
                Field("涨停数", 2, "Number"),
                Field("晋级率", 2, "Percent"),
                Field("打板成功率", 2, "Number", "0.00%"),
            ]))

    class RecordApi:
        def search(self, request):
            return Resp(Data())

        def list(self, request):
            return Resp(Data())

        def create(self, request):
            created.append(request.request_body.fields)
            rec = SimpleNamespace(record_id="rec-new")
            return Resp(SimpleNamespace(record=rec))

    store = BitableStore(
        SimpleNamespace(bitable=SimpleNamespace(v1=SimpleNamespace(
            app_table_field=FieldApi(),
            app_table_record=RecordApi(),
        ))),
        _config(bitable_app_token="app", bitable_table_id="tbl"),
    )
    out = store.upsert_by_date("日期", "2026-09-18", {
        "日期": "2026-09-18",
        "备注": 72,
        "涨停数": "12",
        "晋级率": 40,
        "打板成功率": "62%",
        "龙头": "某龙头",
    })
    assert out["action"] == "create"
    body = created[0]
    assert body["备注"] == "72"
    assert body["涨停数"] == 12
    assert body["晋级率"] == 0.4
    assert body["打板成功率"] == 0.62
    assert "龙头" not in body
