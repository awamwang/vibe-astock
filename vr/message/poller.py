"""消息源后台轮询调度。

财联社由前端主动刷新；选股宝仅手动拉取，不在此自动轮询。
"""

from __future__ import annotations

import threading

_STARTED = False
_LOCK = threading.Lock()


def start_poller(interval: int | None = None) -> None:
    """保留启动钩子以兼容旧部署；当前不启动后台轮询线程。"""
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
