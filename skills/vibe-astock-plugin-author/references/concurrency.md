# 并发与异步写入

在插件使用 WebSocket、轮询线程或任何后台推送时阅读。权威：`doc/development/lock-safety.md`；当前股实现：`duanxian/current_stock.py`。

## 硬规则

1. **读线程只入队**：WS/SSE 读循环里不要同步 `report_current_stock`、`push_messages`、`import_*`、阻塞 `request()` 或重 I/O。
2. **worker 再写入**：从 `queue` 取出后，先 `reg.bind_plugin(pid)`，再调 Registry。
3. **保存 pid**：`on_enable` 结束时引擎会 `unbind_plugin`；后台必须使用启用时保存的 `plugin_id`。
4. **锁外做 IO**：引擎侧锁内只碰内存；插件侧也不要在持锁路径里调会再抢锁的引擎 API。

## 推荐骨架

```python
_REG: HookRegistry | None = None
_PID: str | None = None
_Q: queue.Queue = queue.Queue()

def on_enable(reg: HookRegistry) -> None:
    global _REG, _PID
    _REG, _PID = reg, reg.plugin_id
    reg.register_message_source("my_feed", "我的快讯")
    threading.Thread(target=_worker, daemon=True).start()

def _on_ws_push(msg: dict) -> None:
    _Q.put_nowait(("message", msg))  # 读线程

def _worker() -> None:
    while True:
        kind, payload = _Q.get()
        assert _REG is not None and _PID is not None
        _REG.bind_plugin(_PID)
        if kind == "message":
            _REG.push_messages({...})  # 已转标准格式
        elif kind == "stock":
            _REG.report_current_stock(payload)
```

参考实现：`plugins/vibe-ths-linker/plugin.py`（读线程 + worker 排水）。
