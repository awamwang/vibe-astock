"""电子表格单元格读写。

SDK 的 sheets v3 没有「向单个范围写入数据」，这里走官方 v2 接口。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from .config import LarkConfig
from .errors import raise_if_failed


class SheetStore:
    """读写配置中的那张电子表格。"""

    def __init__(self, client: Any, config: LarkConfig) -> None:
        self._client = client
        self._config = config

    def write_range(self, cell_range: str, values: list[list[Any]]) -> dict[str, Any]:
        """覆盖写入一个范围。cell_range 可写 A1:C2，也可写带工作表前缀的完整范围。"""
        import lark_oapi as lark

        body = {"valueRange": {"range": self._full_range(cell_range), "values": values}}
        request = (
            lark.BaseRequest.builder()
            .http_method(lark.HttpMethod.PUT)
            .uri(f"/open-apis/sheets/v2/spreadsheets/{self._config.spreadsheet_token}/values")
            .token_types({lark.AccessTokenType.TENANT})
            .body(body)
            .build()
        )
        response = self._client.request(request)
        raise_if_failed(response, "写入电子表格")
        return _response_data(response)

    def read_range(self, cell_range: str) -> list[list[Any]]:
        """读取一个范围，返回二维数组。空范围返回空列表。"""
        import lark_oapi as lark

        encoded = quote(self._full_range(cell_range), safe="")
        request = (
            lark.BaseRequest.builder()
            .http_method(lark.HttpMethod.GET)
            .uri(
                "/open-apis/sheets/v2/spreadsheets/"
                f"{self._config.spreadsheet_token}/values/{encoded}"
            )
            .token_types({lark.AccessTokenType.TENANT})
            .build()
        )
        response = self._client.request(request)
        raise_if_failed(response, "读取电子表格")
        data = _response_data(response)
        value_range = data.get("valueRange") if isinstance(data, dict) else None
        values = value_range.get("values") if isinstance(value_range, dict) else None
        return values if isinstance(values, list) else []

    def _full_range(self, cell_range: str) -> str:
        text = cell_range.strip()
        if "!" in text:
            return text
        return f"{self._config.sheet_id}!{text}"


def _response_data(response: Any) -> dict[str, Any]:
    raw = getattr(response, "raw", None)
    content = getattr(raw, "content", None) if raw is not None else None
    if not content:
        return {}
    text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}
