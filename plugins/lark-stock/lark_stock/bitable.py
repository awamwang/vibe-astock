"""多维表格记录的新增、更新、检索和分页列出。"""

from __future__ import annotations

from typing import Any

from .config import LarkConfig
from .errors import LarkApiError, raise_if_failed
from .fields import day_tokens, shanghai_midnight_ms, value_matches_day

_DATE_TYPES = frozenset({5, 1001, 1002})
_DATE_UI = frozenset({"DateTime", "CreatedTime", "ModifiedTime"})
_SCAN_PAGE_LIMIT = 20


class BitableStore:
    """维护配置中的那张多维表格。"""

    def __init__(self, client: Any, config: LarkConfig) -> None:
        self._client = client
        self._config = config

    def create_record(self, fields: dict[str, Any]) -> str:
        """新增一条记录，返回 record_id。"""
        from lark_oapi.api.bitable.v1 import AppTableRecord, CreateAppTableRecordRequest

        request = (
            CreateAppTableRecordRequest.builder()
            .app_token(self._config.bitable_app_token)
            .table_id(self._config.bitable_table_id)
            .request_body(AppTableRecord.builder().fields(fields).build())
            .build()
        )
        response = self._client.bitable.v1.app_table_record.create(request)
        raise_if_failed(response, "新增多维表格记录")
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
            .app_token(self._config.bitable_app_token)
            .table_id(self._config.bitable_table_id)
            .record_id(record_id)
            .request_body(AppTableRecord.builder().fields(fields).build())
            .build()
        )
        response = self._client.bitable.v1.app_table_record.update(request)
        raise_if_failed(response, "更新多维表格记录")

    def list_records(self, *, page_size: int = 100, page_token: str | None = None) -> dict[str, Any]:
        """列出一页记录。还有下一页时返回 page_token。"""
        from lark_oapi.api.bitable.v1 import ListAppTableRecordRequest

        builder = (
            ListAppTableRecordRequest.builder()
            .app_token(self._config.bitable_app_token)
            .table_id(self._config.bitable_table_id)
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

    def _list_fields(self) -> list[Any]:
        from lark_oapi.api.bitable.v1 import ListAppTableFieldRequest

        items: list[Any] = []
        page_token: str | None = None
        for _ in range(10):
            builder = (
                ListAppTableFieldRequest.builder()
                .app_token(self._config.bitable_app_token)
                .table_id(self._config.bitable_table_id)
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
                .app_token(self._config.bitable_app_token)
                .table_id(self._config.bitable_table_id)
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
