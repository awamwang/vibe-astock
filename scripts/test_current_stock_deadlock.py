"""验证 current_stock.report 不会死锁。"""
from __future__ import annotations

import threading

from duanxian import current_stock as cs

cs._current = None  # noqa: SLF001
sub = cs.subscribe()
done: list[bool] = []


def report() -> None:
    cs.report("p1", {"code": "600000", "source": "push"})
    done.append(True)


t = threading.Thread(target=report)
t.start()
t.join(2.0)
print("alive", t.is_alive(), "done", done)
if not t.is_alive():
    print("msg", sub.get(timeout=1.0))
cs.unsubscribe(sub)
print("OK")
