"""验证 current_stock.report 不会死锁。

推荐：`pytest tests/test_lock_safety.py -q`
本脚本为同等场景的手动快捷入口。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
if t.is_alive():
    raise SystemExit(1)
print("OK")
