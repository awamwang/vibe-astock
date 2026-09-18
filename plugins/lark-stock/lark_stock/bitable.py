"""多维表格记录的新增、更新和分页列出。"""

from __future__ import annotations

from typing import Any

from .config import LarkConfig
from .errors import raise_if_failed


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
        items = []
        for record in getattr(data, "items", None) or []:
            items.append(
                {
                    "record_id": str(getattr(record, "record_id", "") or ""),
                    "fields": getattr(record, "fields", None) or {},
                }
            )
        return {
            "items": items,
            "has_more": bool(getattr(data, "has_more", False)),
            "page_token": getattr(data, "page_token", None),
        }
