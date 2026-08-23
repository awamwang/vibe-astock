# 插件开发指南

钩子插件是一个导出 **`PACK`**（`HookPack` 实例）的 Python 文件。引擎在启动时加载，在复盘、预算、验证条件等节点 **推送快照**；插件也可通过 **`HookRegistry`** 向引擎 **写入** 持仓、账户与预算档位。

生命周期与触发顺序见 [hook-lifecycle.md](./hook-lifecycle.md)。

---

## 快速开始

### 1. 编写插件文件

例如 `~/.vibe-astock/plugins/my_bridge.py`：

```python
from __future__ import annotations

import json
from pathlib import Path

from duanxian.hooks import HookContext, HookPack, HookRegistry

_OUT = Path.home() / ".vibe-astock" / "bridge-out"


def on_register(reg: HookRegistry) -> None:
    """进程启动时调用一次；可在此做初始化。"""
    _OUT.mkdir(parents=True, exist_ok=True)


def on_review_saved(ctx: HookContext, envelope: dict) -> None:
    """复盘落盘后收到聚合包。"""
    path = _OUT / f"review-{ctx.date}.json"
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")


PACK = HookPack(
    name="my-bridge",
    version="1.0.0",
    schema_bundle="my-bridge/1.0.0",
    on_register=on_register,
    on_review_saved=on_review_saved,
)
```

### 2. 注册并启用

```bash
python -m duanxian.plugin_cli register ~/.vibe-astock/plugins/my_bridge.py
python -m duanxian.plugin_cli list
```

### 3. 重启 server

```bash
.venv/bin/python server.py
```

注册表：`~/.vibe-astock/plugins.json`。`register` 会校验文件可加载且含合法 `PACK`；**不会**复制文件，请保持路径稳定。

### CLI 子命令

| 命令 | 说明 |
|---|---|
| `list` | 列出 id、启用状态、名称、版本、路径 |
| `register <path>` | 注册；`--disabled` 注册后默认停用 |
| `enable <id\|name>` | 启用（支持 id 前缀或唯一名称） |
| `disable <id\|name>` | 停用 |
| `uninstall <id\|name>` | 从注册表移除（**不删** `.py` 文件） |

---

## `HookPack` 字段

```python
@dataclass(frozen=True)
class HookPack:
    name: str                          # 显示名，注册表内应唯一便于 CLI 操作
    version: str                       # semver 字符串，随插件发布自行维护
    schema_bundle: str                 # 插件理解的 schema 集合标识，便于对账
    metric_providers: tuple[MetricProvider, ...] = ()
    on_register: Callable[[HookRegistry], None] | None = None
    on_metrics_snapshot: Callable[[HookContext, dict], None] | None = None
    on_budget_snapshot: Callable[[HookContext, dict], None] | None = None
    on_verification_snapshot: Callable[[HookContext, dict], None] | None = None
    on_review_saved: Callable[[HookContext, dict], None] | None = None
    enable_review_saved: bool = True   # False 则只收分项快照，不收 review.saved
```

未实现的回调可省略（默认为 `None`）。

### `HookContext`

| 字段 | 说明 |
|---|---|
| `date` | 交易日 `YYYY-MM-DD` |
| `event` | 如 `metrics.snapshot`、`review.saved` |
| `emitted_at` | 发出时间（含时区） |
| `engine_version` | `duanxian.hook_schemas.ENGINE_VERSION` |
| `plugin_id` | 注册表中的 8 位 id |
| `plugin_name` / `plugin_version` | 来自 `PACK` |

### 信封结构（第二参数）

所有 push 回调的 `envelope` 形如：

```json
{
  "$schema": "https://vibe-astock.dev/schemas/hook/envelope/1.0.0",
  "schema_version": "1.0.0",
  "event": "review.saved",
  "date": "2026-01-02",
  "emitted_at": "2026-01-02T22:15:00+08:00",
  "engine_version": "0.1.3",
  "plugin": {
    "id": "a1b2c3d4",
    "name": "my-bridge",
    "version": "1.0.0",
    "schema_bundle": "my-bridge/1.0.0"
  },
  "payload": { }
}
```

业务数据在 `envelope["payload"]`。各事件 payload 的 `$schema` 常量定义在 `duanxian.hook_schemas`。

---

## 订阅类回调：payload 要点

### `metrics.snapshot`

- `scope`：`review` / `live` / `both`（引擎复盘路径固定为 `review`）。
- `sources`：按数据源分块，每块含 `available`、`as_of`、`is_live`、`reason`、`data`。
- `metric_index`：可导出指标的 key、label、unit、path（供外部系统对齐字段）。

常用内置 key 与 JSON 路径映射见 `hooks._BUILTIN_METRIC_PATHS`（如 `limit_up_count` → `emotion_metrics.promotion.limit_up_count`）。

### `verification.snapshot`

- `items`：合并 AI 与用户后的验证条件，含 `base_value`、`eps`、`higher_is_hotter` 等可对账字段。

### `budget.snapshot`

- 仓位六档相关：`phase`、`rule_phase`、`override_phase`、`cap_total_pct`、`cap_single_pct`、`allow` / `forbid` 等。
- **不含** 内部 `readings` 原始读数（刻意剥离，避免插件依赖未稳定字段）。

### `review.saved`

`payload` 内嵌：

```text
review      # 完整复盘 JSON（与 review_store 落盘一致）
metrics     # 同 metrics.snapshot 的 payload
verification
budget      # 可能为 null（预算计算失败时）
```

适合「一次落盘、一次外发」的集成场景。

---

## `HookRegistry`：写入引擎

仅在 `on_register(reg)`（或该回调同步调用的函数）中应持有 `reg`；不要在其他线程长期缓存后随意调用——当前实现无锁，假定单进程单线程复盘。

### `import_portfolio(payload) -> ImportResult`

全量覆盖持仓（`replace` 必须为 `true`）。

```python
reg.import_portfolio({
    "replace": True,
    "holdings": [
        {"code": "600000", "shares": 100, "cost": 10.5},
    ],
    # 可选：equity、note、账户栏位等，校验规则同截图导入 API
})
```

`holdings` 每项需有效 `code`、`shares>0`、`cost>0`；代码不可重复。数据写入 `vr` 模块的 `portfolio`（路径受 `VR_DATA_DIR` 影响）。

### `import_account(payload) -> ImportResult`

更新账户权益与栏位、常量。

```python
reg.import_account({
    "equity": 500000,
    "note": "收盘同步",
    "account_fields": {
        "cash_balance": 120000,
        "daily_pnl": -3500,
    },
    "constants": {
        "risk_per_trade": 0.02,
    },
})
```

顶层也可直接传 `cash_balance`、`daily_pnl` 等键（见 `trade_store._ACCOUNT_FIELD_KEYS`）。仅更新栏位、不改权益时可省略 `equity`。

### `override_budget_phase(date, phase, reason="")`

人手覆盖某日仓位档位。`phase` 须为 `trade_budget.PHASES` 之一；传 `None` 清除覆盖（通过 `trade_store.set_override`）。

### `import_watchlist(payload) -> ImportResult`

全量覆盖自选股（最多 100 只 6 位 A 股代码），写入 `~/.vibe-research/watchlist.json`，并同步盯盘池。

```python
reg.import_watchlist({
    "replace": True,
    "codes": ["600000", "000001"],
})
```

也接受别名字段 `watchlist`（与 `codes` 等价）。`replace` 必须为 `true`（不支持增量合并）。清空列表传 `codes: []`。

前端打开自选股页时会经 `GET /api/watchlist` 拉取；用户在页面上的改动经 `PUT /api/watchlist` 写回。

---

## 注册自定义验证指标：`MetricProvider`

插件可扩展「明日验证条件」可选指标与导出索引：

```python
from duanxian.hooks import MetricProvider, HookPack

def _my_signal(metrics: dict, facts: dict) -> float | None:
    # metrics = emotion_metrics, facts = market_facts
    return (metrics.get("promotion") or {}).get("limit_up_count")

PACK = HookPack(
    name="extra-metrics",
    version="1.0.0",
    schema_bundle="extra-metrics/1.0.0",
    metric_providers=(
        MetricProvider(
            key="my_limit_signal",
            label="自定义涨停读数",
            hint="示例：与内置 limit_up_count 同源",
            eps=3,
            getter=_my_signal,
            higher_is_hotter=True,
            unit="家",
            register_in=frozenset({"verification_menu", "export_index", "ai_pool"}),
            scopes=frozenset({"review"}),
            path=("emotion_metrics", "promotion", "limit_up_count"),
        ),
    ),
)
```

### `register_in` 语义

| 值 | 效果 |
|---|---|
| `verification_menu` | 出现在用户可选验证指标菜单 |
| `export_index` | 进入 `metrics.snapshot` 的 `metric_index`（须同时含 `verification_menu`，否则校验跳过） |
| `ai_pool` | 进入裁判 prompt 的指标池；**启动时会用最近复盘样本 dry-run getter**，算不出值则跳过 |

### 校验与冲突

- `key` 与内置 `verification.builtin_keys()` 冲突 → 跳过。
- 含 `export_index` 但缺 `verification_menu` → 跳过。
- `ai_pool` 无样本或 getter 返回 `None` → 跳过。

通过后由 `verification.register_plugin_metrics` 合并进全局 `METRICS`。

---

## 多插件与错误隔离

- 同一事件对 **每个已启用插件各调用一次**，互不等待，无顺序保证。
- 某插件回调抛错：打印 `⚠️ 钩子回调失败` + traceback，**不影响** 其他插件与复盘事务。
- `on_register` 失败同样只记日志，不阻止其他插件加载。

---

## 依赖与环境

- 插件与引擎 **同一 Python 环境** 运行（同一 venv）。
- 可 `import duanxian.*` 及项目内其他模块；避免在 import 时执行昂贵副作用。
- 插件文件路径建议放在用户目录（如 `~/.vibe-astock/plugins/`），不随仓库分发。

---

## 测试

仓库内 `tests/test_hooks.py` 覆盖：

- 注册表增删改查
- `load_pack_from_path` / `load_plugins`
- `HookRegistry.import_portfolio`
- `build_*_payload` 形状
- `HookRunner.emit_after_review` 多插件扇出
- 回调异常不向外抛出

本地可仿照测试里的 `_PLUGIN_SRC` 与 `plugin_home` fixture 做最小集成验证。

---

## 设计约束（请勿依赖的行为）

1. **无热重载**：改代码或注册表必须重启进程。
2. **复盘路径 budget 不 double-fire**：`refresh(..., emit_hooks=False)` + `emit_after_review` 内统一发 budget。
3. **钩子不是安全边界**：插件与引擎同权，可读写本地数据；仅安装可信代码。
4. **`live` scope 默认不在复盘链路透传**：需要时请插件内自行 `build_metrics_payload("live", ...)`。

---

## 相关源码

| 模块 | 职责 |
|---|---|
| `duanxian/hooks.py` | `HookPack`、`HookRunner`、`HookRegistry`、payload 构建 |
| `duanxian/hook_schemas.py` | `$schema` URL 与版本常量 |
| `duanxian/plugin_store.py` | `plugins.json` 读写 |
| `duanxian/plugin_cli.py` | 命令行管理 |
| `duanxian/verification.py` | 内置与插件指标合并 |
| `server.py` / `main.py` | `emit_after_review` 调用点 |
