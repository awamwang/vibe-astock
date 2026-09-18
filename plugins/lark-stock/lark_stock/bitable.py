"""多维表格记录的新增、更新、检索和分页列出。"""

from __future__ import annotations

import difflib
import unicodedata
from typing import Any

from .config import LarkConfig
from .errors import LarkApiError, raise_if_failed
from .fields import (
    coerce_bitable_value,
    day_tokens,
    shanghai_midnight_ms,
    value_matches_day,
)

_DATE_TYPES = frozenset({5, 1001, 1002})
_DATE_UI = frozenset({"DateTime", "CreatedTime", "ModifiedTime"})
_READONLY_TYPES = frozenset({19, 20, 1001, 1002, 1003, 1004, 1005})
_READONLY_UI = frozenset({
    "Formula", "Lookup", "CreatedTime", "ModifiedTime",
    "CreatedUser", "ModifiedUser", "AutoNumber",
})
_SCAN_PAGE_LIMIT = 20


class BitableStore:
    """维护配置中的那张多维表格。"""

    def __init__(
        self,
        client: Any,
        config: LarkConfig,
        *,
        app_token: str | None = None,
        table_id: str | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._app_token = (app_token or "").strip() or config.bitable_app_token
        self._table_id = (table_id or "").strip() or config.bitable_table_id

    def create_record(self, fields: dict[str, Any]) -> str:
        """新增一条记录，返回 record_id。"""
        from lark_oapi.api.bitable.v1 import AppTableRecord, CreateAppTableRecordRequest

        request = (
            CreateAppTableRecordRequest.builder()
            .app_token(self._app_token)
            .table_id(self._table_id)
            .request_body(AppTableRecord.builder().fields(fields).build())
            .build()
        )
        response = self._client.bitable.v1.app_table_record.create(request)
        self._raise_if_write_failed(response, "新增多维表格记录", fields)
        record = getattr(getattr(response, "data", None), "record", None)
        record_id = getattr(record, "record_id", None)
        if not record_id:
            raise ValueError("新增记录成功但没有返回 record_id")
        return str(record_id)

    def update_record(self, record_id: str, fields: dict[str, Any]) -> None:
        """按 record_id 更新字段。未出现在 fields 里的列保持不变。"""
        from lark_oapi.api.bitable.v1 import AppTableRecord, UpdateAppTableRecordRequest

        request = (
            UpdateAppTableRecordRequest.builder()
            .app_token(self._app_token)
            .table_id(self._table_id)
            .record_id(record_id)
            .request_body(AppTableRecord.builder().fields(fields).build())
            .build()
        )
        response = self._client.bitable.v1.app_table_record.update(request)
        self._raise_if_write_failed(response, "更新多维表格记录", fields)

    def list_records(self, *, page_size: int = 100, page_token: str | None = None) -> dict[str, Any]:
        """列出一页记录。还有下一页时返回 page_token。"""
        from lark_oapi.api.bitable.v1 import ListAppTableRecordRequest

        builder = (
            ListAppTableRecordRequest.builder()
            .app_token(self._app_token)
            .table_id(self._table_id)
            .page_size(page_size)
        )
        if page_token:
            builder = builder.page_token(page_token)
        response = self._client.bitable.v1.app_table_record.list(builder.build())
        raise_if_failed(response, "列出多维表格记录")
        data = getattr(response, "data", None)
        return {
            "items": _record_items(data),
            "has_more": bool(getattr(data, "has_more", False)),
            "page_token": getattr(data, "page_token", None),
        }

    def find_by_date(self, field_name: str, day: str) -> list[dict[str, Any]]:
        """找出日期列等于指定日的记录。日期类型用当天 0 点筛选，文本列再按常见写法扫描。"""
        name = str(field_name or "").strip()
        if not name:
            raise ValueError("日期列名未配置")
        kind = self._field_kind(name)
        if kind == "missing":
            raise ValueError(f"多维表格里没有列「{name}」")
        if kind in {"date", "unknown"}:
            try:
                rows = self._search_field(name, ["ExactDate", str(shanghai_midnight_ms(day))])
            except LarkApiError:
                if kind == "date":
                    raise
            else:
                if rows or kind == "date":
                    return rows
        found = self._search_text_day(name, day)
        if found:
            return found
        return self._scan_day(name, day)

    def upsert_by_date(self, field_name: str, day: str, fields: dict[str, Any]) -> dict[str, Any]:
        """按日期列新增或更新。已有多条时更新最先找到的那条。"""
        name = str(field_name or "").strip()
        if not name:
            raise ValueError("日期列名未配置")
        body = {str(k): v for k, v in (fields or {}).items() if str(k).strip()}
        kind = self._field_kind(name)
        if kind == "date":
            body[name] = shanghai_midnight_ms(day)
        else:
            body.setdefault(name, day)
        body, unknown, catalog = self._writable_fields(body)
        existing = self.find_by_date(name, day)
        if existing:
            record_id = str(existing[0].get("record_id") or "")
            if not record_id:
                raise ValueError("已有记录但缺少 record_id")
            self.update_record(record_id, body)
            result = {"action": "update", "record_id": record_id, "matched": len(existing), "fields": body}
        else:
            record_id = self.create_record(body)
            result = {"action": "create", "record_id": record_id, "matched": 0, "fields": body}
        if unknown:
            result["skipped"] = unknown
            result["hint"] = _unknown_fields_message(unknown, catalog, skipped=True)
        return result

    def _field_kind(self, field_name: str) -> str:
        """列类型：date / text / missing / unknown。列清单读失败时为 unknown。"""
        try:
            fields = self._list_fields()
        except LarkApiError:
            return "unknown"
        for field in fields:
            if str(getattr(field, "field_name", "") or "") != field_name:
                continue
            ui = str(getattr(field, "ui_type", "") or "")
            ftype = getattr(field, "type", None)
            if ui in _DATE_UI or ftype in _DATE_TYPES:
                return "date"
            return "text"
        return "missing"

    def _field_catalog(self) -> dict[str, tuple[str, Any, str]]:
        """列名 → (kind, type, ui_type)。列清单读失败时为空。"""
        try:
            fields = self._list_fields()
        except LarkApiError:
            return {}
        catalog: dict[str, tuple[str, Any, str]] = {}
        for field in fields:
            name = str(getattr(field, "field_name", "") or "")
            if not name.strip():
                continue
            ui = str(getattr(field, "ui_type", "") or "")
            ftype = getattr(field, "type", None)
            if ui in _DATE_UI or ftype in _DATE_TYPES:
                kind = "date"
            elif _is_percent_field(ui, field):
                kind = "percent"
            elif ftype == 2 or ui in {"Number", "Currency", "Rating"}:
                kind = "number"
            else:
                kind = "text"
            catalog[name] = (kind, ftype, ui)
        return catalog

    def _writable_fields(self, fields: dict[str, Any]) -> tuple[dict[str, Any], list[str], dict[str, tuple[str, Any, str]]]:
        """丢掉表里没有的列和公式/系统列。没有的列名留给调用方提示。"""
        catalog = self._field_catalog()
        if not catalog:
            return fields, [], catalog
        out: dict[str, Any] = {}
        unknown: list[str] = []
        for name, value in fields.items():
            actual = _canonical_field_name(name, catalog)
            if actual is None:
                unknown.append(name)
                continue
            _kind, ftype, ui = catalog[actual]
            if ftype in _READONLY_TYPES or ui in _READONLY_UI:
                continue
            converted = coerce_bitable_value(value, _kind)
            if converted is None:
                continue
            out[actual] = converted
        return out, unknown, catalog

    def _raise_if_write_failed(self, response: Any, action: str, fields: dict[str, Any]) -> None:
        """写入失败时，尽量补上表里对不上的列名。"""
        try:
            raise_if_failed(response, action)
        except LarkApiError as exc:
            if exc.code not in {1254045, 1254060, 1254061}:
                raise
            catalog = self._field_catalog()
            if exc.code == 1254045:
                if not catalog:
                    names = "、".join(f"「{name}」" for name in fields)
                    extra = f"飞书未指出具体列；本次写入了：{names}。请对照表格实际列名。"
                else:
                    unknown = [
                        name for name in fields if _canonical_field_name(name, catalog) is None
                    ]
                    extra = (
                        _unknown_fields_message(unknown, catalog)
                        if unknown
                        else "请核对列名是否完全一致，或检查高级权限是否隐藏了部分列。"
                    )
            else:
                extra = (
                    "数字列须传 JSON 数字，百分比列传 0.5 表示 50%，文本列传字符串。"
                    "请核对写入值是否与列类型一致。"
                )
            raise LarkApiError(action, exc.code, f"{exc.msg}。{extra}", exc.log_id) from exc

    def _list_fields(self) -> list[Any]:
        from lark_oapi.api.bitable.v1 import ListAppTableFieldRequest

        items: list[Any] = []
        page_token: str | None = None
        for _ in range(10):
            builder = (
                ListAppTableFieldRequest.builder()
                .app_token(self._app_token)
                .table_id(self._table_id)
                .page_size(100)
            )
            if page_token:
                builder = builder.page_token(page_token)
            response = self._client.bitable.v1.app_table_field.list(builder.build())
            raise_if_failed(response, "列出多维表格字段")
            data = getattr(response, "data", None)
            items.extend(getattr(data, "items", None) or [])
            if not getattr(data, "has_more", False):
                return items
            page_token = getattr(data, "page_token", None)
            if not page_token:
                return items
        return items

    def _search_field(self, field_name: str, value: list[str]) -> list[dict[str, Any]]:
        from lark_oapi.api.bitable.v1 import (
            Condition,
            FilterInfo,
            SearchAppTableRecordRequest,
            SearchAppTableRecordRequestBody,
        )

        filt = (
            FilterInfo.builder()
            .conjunction("and")
            .conditions([
                Condition.builder().field_name(field_name).operator("is").value(value).build(),
            ])
            .build()
        )
        found: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(5):
            builder = (
                SearchAppTableRecordRequest.builder()
                .app_token(self._app_token)
                .table_id(self._table_id)
                .page_size(100)
                .request_body(SearchAppTableRecordRequestBody.builder().filter(filt).build())
            )
            if page_token:
                builder = builder.page_token(page_token)
            response = self._client.bitable.v1.app_table_record.search(builder.build())
            raise_if_failed(response, "检索多维表格记录")
            data = getattr(response, "data", None)
            found.extend(_record_items(data))
            if not getattr(data, "has_more", False):
                return found
            page_token = getattr(data, "page_token", None)
            if not page_token:
                return found
        return found

    def _search_text_day(self, field_name: str, day: str) -> list[dict[str, Any]]:
        tokens = day_tokens(day)
        for token in (tokens[0], tokens[1]):
            try:
                rows = self._search_field(field_name, [token])
            except LarkApiError:
                return []
            if rows:
                return rows
        return []

    def _scan_day(self, field_name: str, day: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(_SCAN_PAGE_LIMIT):
            page = self.list_records(page_size=100, page_token=page_token)
            for item in page["items"]:
                fields = item.get("fields") or {}
                if value_matches_day(fields.get(field_name), day):
                    found.append(item)
            if not page["has_more"]:
                return found
            page_token = page.get("page_token")
            if not page_token:
                return found
        return found


def _record_items(data: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for record in getattr(data, "items", None) or []:
        fields = getattr(record, "fields", None) or {}
        if not isinstance(fields, dict):
            fields = {}
        items.append({
            "record_id": str(getattr(record, "record_id", "") or ""),
            "fields": fields,
        })
    return items


def _norm_field_name(name: str) -> str:
    return unicodedata.normalize("NFKC", str(name or "")).strip()


def _field_formatter(field: Any) -> str:
    prop = getattr(field, "property", None)
    if prop is None:
        return ""
    if isinstance(prop, dict):
        return str(prop.get("formatter") or "")
    return str(getattr(prop, "formatter", "") or "")


def _is_percent_field(ui: str, field: Any) -> bool:
    if ui in {"Percent", "Progress"}:
        return True
    return "%" in _field_formatter(field)


def _canonical_field_name(name: str, catalog: dict[str, Any]) -> str | None:
    """把配置里的列名对到表格真实列名。只差空格/全半角时用表里的写法。"""
    if name in catalog:
        return name
    target = _norm_field_name(name)
    if not target:
        return None
    for actual in catalog:
        if _norm_field_name(actual) == target:
            return actual
    return None


def _unknown_fields_message(
    unknown: list[str],
    catalog: dict[str, Any],
    *,
    skipped: bool = False,
) -> str:
    actual = [str(name) for name in catalog]
    parts: list[str] = []
    for name in unknown:
        close = difflib.get_close_matches(
            _norm_field_name(name),
            [_norm_field_name(item) for item in actual],
            n=1,
            cutoff=0.5,
        )
        if close:
            original = next(
                (item for item in actual if _norm_field_name(item) == close[0]),
                close[0],
            )
            parts.append(f"「{name}」→接近「{original}」")
        else:
            parts.append(f"「{name}」")
    lead = "已跳过表里没有的列：" if skipped else "多维表格里没有这些列："
    return (
        lead
        + "、".join(parts)
        + "。请把插件配置里的列名改成与表格完全一致（含空格和符号）。"
    )
