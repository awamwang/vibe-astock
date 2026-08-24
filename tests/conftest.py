"""测试全局约束：**禁止出站网络**。

本目录只测纯逻辑。一旦某条测试忘了 patch 数据源（比如 `latest_session()` 内部
会去打腾讯行情判断今天是否开市），它就会变成"依赖网络 + 依赖今天是不是交易日"
的脆弱测试——平时绿、周末或断网时红，而且失败原因看不出来。
这里直接把 connect 拦掉：谁漏了 patch 就当场以明确信息失败。
"""

from __future__ import annotations

import socket

import pytest


# 回环地址放行。Windows 的 asyncio 事件循环用 `socketpair()` 建自管道，而它在
# Windows 上就是一条连到 127.0.0.1 的 TCP —— 一刀拦掉的话，凡是用 `TestClient`
# 的测试连启动都启动不了（报的还是"出站网络"，指向完全错误的方向）。
# 拦的目标是**外部数据源**，回环够不到任何数据源。
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    real_connect = socket.socket.connect

    def blocked(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in _LOOPBACK:
            return real_connect(self, address, *args, **kwargs)
        raise AssertionError(
            "测试期间不允许出站网络连接 —— 说明有数据源没被 patch，请补上 monkeypatch"
        )

    monkeypatch.setattr(socket.socket, "connect", blocked, raising=False)
