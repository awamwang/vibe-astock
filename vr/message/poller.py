"""消息源后台轮询调度。"""

from __future__ import annotations

import os
import threading
import time

from . import store
from . import xgb

_STARTED = False
_LOCK = threading.Lock()


def _poll_once() -> None:
    try:
        xgb.fetch_pc_msgs()
    except Exception as e:  # noqa: BLE001
        store.set_poll_state("xgb_msgs", last_error=str(e)[:500])


def _loop(interval: int) -> None:
    while True:
        time.sleep(interval)
        sources = store.list_sources()
        for s in sources:
            if not s.enabled or s.adapter_type != "poll" or s.id != "xgb_msgs":
                continue
            sec = s.poll_interval_s or interval
            # 简化：统一间隔线程，按 source 配置决定是否执行
            if s.id == "xgb_msgs":
                try:
                    xgb.fetch_pc_msgs()
                except Exception as e:  # noqa: BLE001
                    store.set_poll_state("xgb_msgs", last_error=str(e)[:500])


def start_poller(interval: int | None = None) -> None:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    sec = interval or int(os.environ.get("MESSAGE_POLL_INTERVAL", "30"))
    threading.Thread(target=_loop, args=(sec,), daemon=True, name="message-poller").start()
