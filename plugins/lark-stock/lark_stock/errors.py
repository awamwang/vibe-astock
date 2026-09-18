"""飞书调用失败时的统一异常。"""

from __future__ import annotations

from typing import Any


class ConfigError(RuntimeError):
    """环境变量缺失或取值不合法。"""


class LarkApiError(RuntimeError):
    """开放平台返回失败。"""

    def __init__(self, action: str, code: int | None, msg: str, log_id: str | None = None) -> None:
        self.action = action
        self.code = code
        self.log_id = log_id
        detail = f"{action}失败：{msg or '未知错误'}（code={code}"
        if log_id:
            detail += f", log_id={log_id}"
        detail += "）"
        super().__init__(detail)


def raise_if_failed(response: Any, action: str) -> None:
    """响应不成功时抛出带 code / log_id 的错误。"""
    success = getattr(response, "success", None)
    if callable(success) and success():
        return
    log_id = None
    getter = getattr(response, "get_log_id", None)
    if callable(getter):
        log_id = getter()
    raise LarkApiError(
        action,
        getattr(response, "code", None),
        str(getattr(response, "msg", "") or ""),
        log_id,
    )
