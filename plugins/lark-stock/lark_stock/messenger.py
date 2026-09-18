"""发送文本消息。"""

from __future__ import annotations

import json
from typing import Any

from .config import LarkConfig
from .errors import raise_if_failed


class Messenger:
    """按配置的接收方发送文本消息。"""

    def __init__(self, client: Any, config: LarkConfig) -> None:
        self._client = client
        self._config = config

    def send_text(
        self,
        text: str,
        *,
        receive_id: str | None = None,
        receive_id_type: str | None = None,
    ) -> str:
        """发送一条文本消息，返回 message_id。"""
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type or self._config.im_receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id or self._config.im_receive_id)
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .build()
            )
            .build()
        )
        response = self._client.im.v1.message.create(request)
        raise_if_failed(response, "发送消息")
        message_id = getattr(getattr(response, "data", None), "message_id", None)
        if not message_id:
            raise ValueError("发送消息成功但没有返回 message_id")
        return str(message_id)
