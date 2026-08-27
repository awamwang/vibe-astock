"""锁安全：死锁回归 + 持锁调用静态扫描。"""

from __future__ import annotations

import threading
import time

import pytest

from duanxian import current_stock as cs
from duanxian import lock_safety_check as lsc
from duanxian.hooks import HookRegistry


def _join_or_fail(thread: threading.Thread, *, timeout: float, label: str) -> None:
    thread.join(timeout)
    assert not thread.is_alive(), label


@pytest.mark.unit
class TestCurrentStockDeadlockRegression:
    def test_subscribe_empty_state_no_deadlock(self):
        """回归：_current 为空时 subscribe 不得自死锁（原 bug：to_dict(None) 内再 get_current）。"""
        cs._current = None  # noqa: SLF001
        done = threading.Event()

        def _subscribe() -> None:
            cs.subscribe()
            done.set()

        t = threading.Thread(target=_subscribe)
        t.start()
        assert done.wait(timeout=2.0), "subscribe 在 _current=None 时自死锁"
        _join_or_fail(t, timeout=0.5, label="subscribe 线程未退出")

    def test_subscribe_while_report_no_deadlock(self):
        """回归：SSE subscribe 与插件 report 并发不得互锁。"""
        cs._current = None  # noqa: SLF001
        sub = cs.subscribe()
        reg = HookRegistry()
        reg.bind_plugin("plug-deadlock")
        err: list[Exception] = []

        def _report() -> None:
            try:
                reg.report_current_stock({"code": "600519", "source": "push"})
            except Exception as exc:  # noqa: BLE001
                err.append(exc)

        t = threading.Thread(target=_report)
        t.start()
        _join_or_fail(t, timeout=2.0, label="report_current_stock 与 subscribe 并发死锁")
        assert not err
        msg = sub.get(timeout=1.0)
        assert msg is not None
        assert msg["code"] == "600519"
        cs.unsubscribe(sub)

    def test_to_dict_none_under_held_lock_returns_fast(self):
        """显式 to_dict(None) 在已持锁时须立即返回 None，不得阻塞。"""
        cs._lock.acquire()
        try:
            start = time.monotonic()
            assert cs.to_dict(None) is None
            assert time.monotonic() - start < 0.2
        finally:
            cs._lock.release()


@pytest.mark.unit
def test_lock_hold_static_scan_clean():
    """持锁块内不得调用同模块内也会抢同一把锁的函数。"""
    violations = lsc.scan_paths(lsc.default_scan_paths())
    text = lsc.format_violations(violations)
    assert not violations, f"发现持锁重入风险：\n{text}"
