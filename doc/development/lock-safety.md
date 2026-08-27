# 锁安全与死锁防护

> 并发锁总览见 [architecture.md §6](./architecture.md#6-并发与加锁)。本文说明 **如何避免自死锁**、**如何写回归测试**、**如何用静态扫描兜底**。

本项目为 **单进程 + 多线程**（FastAPI 同步路由、后台 `threading.Thread`、插件 WebSocket 读线程）。锁均为 **`threading.Lock`（非可重入）**，同一线程在持锁时再抢同一把锁会 **永久自死锁**。

---

## 1. 典型故障模式

### 1.1 持锁重入（同线程自死锁）

```python
# ❌ subscribe 持 _lock 时调 to_dict(None)
# to_dict 把 None 当成「未传参」→ get_current() → 再抢 _lock
with _lock:
    snap = to_dict(_current)  # _current 为 None 时必死锁
```

**修复要点：**

- 锁内只读原始状态（如 `rec = _current`），序列化放到锁外。
- 可选参数若需区分「未传」与「显式 None」，用 **sentinel**（如 `_MISSING = object()`），勿用 `None` 兼作默认值。

### 1.2 IO 读线程同步重活（间接卡死全进程）

WebSocket / SSE **读线程**里若同步调用 `report_current_stock()`、文件 I/O、或 `_client.request()`：

1. 读线程阻塞，无法继续 `recv()`，响应队列无人消费；
2. 其他线程在 `request()` 上等待响应 → **整条链路卡死**。

**修复要点：** 读线程 **只入队**；业务逻辑交给独立 worker（参见 `plugins/vibe-ths-linker/plugin.py` 的 `_push_worker`）。

### 1.3 跨线程互锁

线程 A：`subscribe()` 自死锁并一直占 `_lock`  
线程 B：插件 `report_current_stock()` 等 `_lock` → 永久阻塞  

表现为 **服务端整体无响应**，而不只是单个 API 慢。

---

## 2. 编码约定

| 规则 | 说明 |
|------|------|
| **锁内最小化** | 锁内仅读写内存结构；网络、磁盘、钩子回调、队列通知放在锁外 |
| **禁止锁内再调「会抢同锁」的函数** | 同模块内凡含 `with _lock:` 的函数，不得在另一函数的 `with _lock:` 块内直接调用 |
| **None 语义分离** | `def fn(x=None)` 若 `None` 既是合法值又表示默认，改用 sentinel |
| **IO 回调只入队** | WS push、定时器、读线程 → `queue` + worker，不在回调里 `request()` / 持锁上报 |
| **并发改锁必补测试** | 至少一个「带 `timeout` 的线程 join / Event.wait」回归用例 |

---

## 3. 自动化防护（固定手段）

### 3.1 回归测试

`tests/test_lock_safety.py`：

- `_current=None` 时 `subscribe()` 不卡死；
- `subscribe` 与 `report_current_stock` 并发不互锁；
- 持锁时 `to_dict(None)` 立即返回。

手工快捷入口（可选）：

```bash
python scripts/test_current_stock_deadlock.py
```

### 3.2 静态扫描

`duanxian/lock_safety_check.py` 用 AST 扫描：**在 `with _lock:` 块内是否调用了同模块内也会抢同一把锁的函数**。

```bash
python scripts/check_lock_holds.py
# 或
pytest tests/test_lock_safety.py::test_lock_hold_static_scan_clean -q
```

扫描范围：`duanxian/`、`plugins/`、`vr/`、`server.py`。

**局限：** 无法覆盖跨模块锁顺序、类属性锁（`self._x_lock`）的全部组合；新增锁模块时酌情扩展扫描路径或补集成测试。

### 3.3 Lint

Ruff **无法** 理解锁语义，**不能**替代上述测试与扫描。持锁问题靠 **测试 + AST 扫描 + 代码评审**。

---

## 4. 排查清单（人工）

怀疑死锁时按序检查：

1. **哪把锁？** 看模块顶部 `_lock` / `_LOCK` 与 architecture §6.1 表。
2. **谁持锁？** 在 `with _lock:` 内打了哪些调用？是否再次进入同模块带锁函数？
3. **哪条线程？** WS 读线程、插件 bridge、SSE `subscribe`、FastAPI worker 是否交叉等待。
4. **能否超时复现？** 写最小 `threading.Thread` + `join(timeout=2)` 脚本或 pytest。
5. **修复后：** 补 `tests/test_lock_safety.py` 用例；跑 `python scripts/check_lock_holds.py`。

---

## 5. 参考实现

| 场景 | 文件 | 做法 |
|------|------|------|
| 当前股票 SSE + 插件上报 | `duanxian/current_stock.py` | sentinel + 锁外 `to_dict(rec)` |
| 同花顺 WS push | `plugins/vibe-ths-linker/plugin.py` | `_push_queue` + `_push_worker` |
| 板块 refresh 并发 | `tests/test_ths_block.py` | `Event.wait(timeout=5)` 防死锁回归 |

---

## 6. 相关文档

- [architecture.md §6](./architecture.md#6-并发与加锁) — 锁一览与缓存双检模式  
- [plugin-development.md](./plugin-development.md) — 插件写入 API（含 `report_current_stock`）  
- [hook-lifecycle.md](./hook-lifecycle.md) — 插件线程与引擎交互时机  
