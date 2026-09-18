"""飞书调用失败时的统一异常。"""

from __future__ import annotations

from typing import Any


_CODE_HINTS = {
    91403: (
        "当前应用没有这张多维表格的编辑权限。"
        "请打开该表格 → 右上角「…」→「添加文档应用」，搜到本应用并设为「可编辑」；"
        "若表格开了高级权限，还需给应用「可管理」，并允许新增记录。"
    ),
}


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
        hint = _CODE_HINTS.get(code) if code is not None else None
        if hint:
            detail += f"。{hint}"
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
