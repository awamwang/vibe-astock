# 插件开发指南

钩子插件是一个导出 **`PACK`**（`HookPack` 实例）的 Python 文件。引擎在启动时加载，在复盘、预算、验证条件等节点 **推送快照**；插件也可通过 **`HookRegistry`** 向引擎 **写入** 持仓、账户与预算档位。

生命周期与触发顺序见 [hook-lifecycle.md](./hook-lifecycle.md)。

---

## 索引

### 推送回调（引擎 → 插件）

| 回调 / 配置 | 事件名 | 详表 |
|---|---|---|
| `on_register` | —（兼容旧插件，等同 `on_enable`） | [附录 A.1](#a1-on_register) |
| `on_enable` | —（插件激活） | [附录 A.7](#a7-on_enable) |
| `on_disable` | —（插件停用） | [附录 A.8](#a8-on_disable) |
| `on_metrics_snapshot` | `metrics.snapshot` | [附录 A.2](#a2-on_metrics_snapshot) |
| `on_verification_snapshot` | `verification.snapshot` | [附录 A.3](#a3-on_verification_snapshot) |
| `on_budget_snapshot` | `budget.snapshot` | [附录 A.4](#a4-on_budget_snapshot) |
| `on_review_saved` | `review.saved` | [附录 A.5](#a5-on_review_saved) |
| `enable_review_saved` | —（控制是否收聚合事件） | [附录 A.6](#a6-enable_review_saved) |

### 写入接口（插件 → 引擎）

| 方法 | 详表 |
|---|---|
| `import_portfolio` | [附录 B.1](#b1-import_portfolio) |
| `import_account` | [附录 B.2](#b2-import_account) |
| `override_budget_phase` | [附录 B.3](#b3-override_budget_phase) |
| `import_watchlist` | [附录 B.4](#b4-import_watchlist) |
| `report_status` | [附录 B.5](#b5-report_status) |

### 扩展指标

| 机制 | 详表 |
|---|---|
| `MetricProvider` / `metric_providers` | [附录 C.1](#c1-metricprovider) |

### 公共类型

| 类型 | 详表 |
|---|---|
| `HookPack` 字段总览 | [附录 D.1](#d1-hookpack) |
| `HookContext` | [附录 D.2](#d2-hookcontext) |
| 信封 `envelope` | [附录 D.3](#d3-envelope) |

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

## `HookRegistry` 写入要点

仅在 `on_register(reg)`（或该回调同步调用的函数）中应持有 `reg`；不要在其他线程长期缓存后随意调用——当前实现无锁，假定单进程单线程复盘。

各写入方法的 payload 形状、对应页面与 API 见 [附录 B](#附录-b-写入接口插件--引擎)。

---

## 注册自定义验证指标

插件可通过 `metric_providers` 扩展「明日验证条件」可选指标与导出索引。字段语义、`register_in` 取值与校验规则见 [附录 C.1](#c1-metricprovider)。

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

1. **代码无热重载**：改 `.py` 源码须重启进程；启用/停用/卸载经 API 可即时生效（调用 `on_enable` / `on_disable`）。
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
| `duanxian/plugin_status.py` | 运行状态存储与 API 合成 |
| `duanxian/plugin_cli.py` | 命令行管理 |
| `duanxian/verification.py` | 内置与插件指标合并 |
| `server.py` / `main.py` | `emit_after_review` 调用点 |

---

## 附录 A：推送回调（引擎 → 插件）

以下每条采用统一结构：**中文作用**、**触发时机**、**对应页面与 API**、**回调签名**、**数据结构**。

---

### A.1 `on_register` {#a1-on_register}

| 项 | 说明 |
|---|---|
| **中文作用** | 进程启动、插件加载成功后调用一次；用于初始化（建目录、预连外部服务等），并向引擎 **写入** 持仓、账户、预算档位、自选股。 |
| **HookPack 字段** | `on_register` |
| **触发时机** | 进程启动加载已启用插件时调用；与 `on_enable` 二选一即可，若两者都实现则仅调用 `on_enable`。 |
| **对应页面** | 无直接 UI；写入结果体现在 [持仓与预算](/trade)、[自选股](/watchlist)、[复盘看板](/agent/review) 预算卡等页面下次打开时的数据。 |
| **对应 API** | 写入侧等价于 `POST /api/trade/screenshot/apply`、`POST /api/trade/account/*`、`POST /api/trade/budget/override`、`PUT /api/watchlist`（插件不经 HTTP，直接调 `HookRegistry`）。 |
| **回调签名** | `on_register(reg: HookRegistry) -> None` |
| **信封 / payload** | 无第二参数；通过 `reg` 调用 [附录 B](#附录-b-写入接口插件--引擎) 中的方法。 |

---

### A.7 `on_enable` {#a7-on_enable}

| 项 | 说明 |
|---|---|
| **中文作用** | 插件被激活时调用：进程启动加载、插件管理页启用、API `POST /api/plugins/enable` 注册后启用。用于启动后台任务、连接外部服务等。 |
| **HookPack 字段** | `on_enable` |
| **触发时机** | `apply_plugin_enable` 或进程 `_init()` 加载已启用插件时；优先于 `on_register`。 |
| **回调签名** | `on_enable(reg: HookRegistry) -> None` |
| **信封 / payload** | 同 `on_register`，通过 `reg` 写入引擎。 |

---

### A.8 `on_disable` {#a8-on_disable}

| 项 | 说明 |
|---|---|
| **中文作用** | 插件被停用时调用：释放连接、停止后台线程、清理临时资源。 |
| **HookPack 字段** | `on_disable` |
| **触发时机** | 插件管理页停用、API `POST /api/plugins/disable`、卸载前 `apply_plugin_disable`。 |
| **回调签名** | `on_disable() -> None` |
| **信封 / payload** | 无参数。停用后插件从 `RUNNER` 移除，不再接收 push 事件。 |

---

### A.2 `on_metrics_snapshot` {#a2-on_metrics_snapshot}

| 项 | 说明 |
|---|---|
| **中文作用** | 推送当日盘面指标快照：情绪读数、市场事实、短线盘面、宽度、情绪块等，并附带可导出指标索引，供外部系统对齐字段。 |
| **HookPack 字段** | `on_metrics_snapshot` |
| **事件名** | `metrics.snapshot` |
| **触发时机** | ① 复盘保存后 `emit_after_review` 第一步；② 可单独 `RUNNER.emit_metrics(...)`（引擎内部或插件自调）。复盘路径固定 `scope=review`。 |
| **对应页面** | [短线盘面](/short-board)、[盘面数据](/daily-review)、[首板分析](/first-board)、[多日情绪](/heat)、[复盘看板](/agent/review) 中的情绪指标卡与市场事实面板（数据同源）。 |
| **对应 API** | 复盘触发：`POST /api/review/run`（[复盘看板](/agent/review)「运行复盘」）。 |
| **回调签名** | `on_metrics_snapshot(ctx: HookContext, envelope: dict) -> None` |

**`envelope["payload"]` 结构**（`$schema` = `metrics-snapshot/1.0.0`）：

```json
{
  "$schema": "https://vibe-astock.dev/schemas/hook/metrics-snapshot/1.0.0",
  "schema_version": "1.0.0",
  "scope": "review",
  "date": "2026-01-02",
  "sources": {
    "emotion_metrics": {
      "available": true,
      "as_of": "2026-01-02",
      "is_live": false,
      "reason": null,
      "data": { }
    },
    "market_facts": { "available": true, "as_of": "...", "is_live": false, "reason": null, "data": { } },
    "short_board": { },
    "breadth": { },
    "mood_blocks": { }
  },
  "metric_index": [
    {
      "key": "limit_up_count",
      "label": "涨停家数",
      "unit": "家",
      "scope": "review",
      "verifiable": true,
      "path": ["emotion_metrics", "promotion", "limit_up_count"]
    }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `scope` | `review` / `live` / `both`；复盘链路透传为 `review`。 |
| `sources` | 按数据源分块；每块含 `available`、`as_of`、`is_live`、`reason`、`data`。 |
| `sources.emotion_metrics` / `market_facts` | 来自复盘 JSON，与 [复盘看板](/agent/review) 展示一致。 |
| `sources.short_board` / `breadth` / `mood_blocks` | 复盘保存时现场拉取；对应 [短线盘面](/short-board) 等页。 |
| `metric_index` | 可导出指标清单；内置 key 与 JSON 路径见 `hooks._BUILTIN_METRIC_PATHS`。 |

`scope=live` 时额外含 `sources.live_emotion`（实时情绪）；插件可自行 `build_metrics_payload("live", date, review)` 获取。

---

### A.3 `on_verification_snapshot` {#a3-on_verification_snapshot}

| 项 | 说明 |
|---|---|
| **中文作用** | 推送「明日验证条件」快照：合并 AI 产出与用户自设后的条件列表，并附带当日基准值、容差 `eps`、方向语义，便于次日对账。 |
| **HookPack 字段** | `on_verification_snapshot` |
| **事件名** | `verification.snapshot` |
| **触发时机** | ① 复盘保存后 `emit_after_review` 第二步；② 用户在 [复盘看板](/agent/review) 保存自设验证条件后单独触发（不重跑整包复盘钩子）。 |
| **对应页面** | [复盘看板](/agent/review) —「我自己的验证条件」编辑区；页内 AI 产出的 `focus.verification_items` 只读展示。 |
| **对应 API** | `GET /api/verification/menu`、`GET/POST /api/verification/items?date=` |
| **回调签名** | `on_verification_snapshot(ctx: HookContext, envelope: dict) -> None` |

**`envelope["payload"]` 结构**（`$schema` = `verification-snapshot/1.0.0`）：

```json
{
  "$schema": "https://vibe-astock.dev/schemas/hook/verification-snapshot/1.0.0",
  "schema_version": "1.0.0",
  "date": "2026-01-02",
  "items": [
    {
      "metric": "limit_up_count",
      "direction": "上升",
      "reason": "判升温则涨停家数应抬升",
      "by": "ai",
      "label": "涨停家数",
      "unit": "家",
      "eps": 5,
      "base_value": 40,
      "higher_is_hotter": true
    }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `items[].metric` | 指标 key，须在验证菜单内（内置 + 插件 `MetricProvider`）。 |
| `items[].direction` | `上升` / `下降` / `持平`。 |
| `items[].by` | `ai` 或 `user`；同一 `metric` 用户覆盖 AI。 |
| `items[].base_value` | 落盘日基准读数（对账起点）。 |
| `items[].eps` | 「变了才算变」阈值。 |
| `items[].higher_is_hotter` | 数值升高是否代表情绪更热（UI 提示用）。 |

---

### A.4 `on_budget_snapshot` {#a4-on_budget_snapshot}

| 项 | 说明 |
|---|---|
| **中文作用** | 推送当日 **仓位预算六档** 结果：生效档位、规则档、手拨覆盖、总仓/单票上限、允许/禁止动作、扩张闸门等；**不含** 内部 `readings` 原始读数。 |
| **HookPack 字段** | `on_budget_snapshot` |
| **事件名** | `budget.snapshot` |
| **触发时机** | ① 复盘保存后 `emit_after_review` 第三步（`budget_env` 非空时）；② `trade_store.refresh(date)` 且 `emit_hooks=True`（如 [持仓与预算](/trade) 点「刷新预算」）。复盘主路径用 `emit_hooks=False` 避免重复触发。 |
| **对应页面** | [持仓与预算](/trade) 预算卡与档位说明；[复盘看板](/agent/review) 内嵌 `TradeBudgetCard`。 |
| **对应 API** | `GET /api/trade/budget`、`POST /api/trade/budget/refresh`、`POST /api/trade/budget/override`、`GET /api/trade/phases` |
| **回调签名** | `on_budget_snapshot(ctx: HookContext, envelope: dict) -> None` |

**`envelope["payload"]` 结构**（`$schema` = `budget-snapshot/1.0.0`）：

```json
{
  "$schema": "https://vibe-astock.dev/schemas/hook/budget-snapshot/1.0.0",
  "schema_version": "1.0.0",
  "date": "2026-01-02",
  "available": true,
  "reason": null,
  "phase": "升温扩张",
  "rule_phase": "升温扩张",
  "override_phase": null,
  "override_reason": null,
  "cap_total_pct": 0.6,
  "cap_single_pct": 0.1,
  "allow": ["顺势加仓", "持有核心"],
  "forbid": ["逆势抄底杂毛"],
  "expansion_allowed": true,
  "demoted": false,
  "classify_reasons": ["..."],
  "width_divergence": { "hit": false },
  "repair_proxy": { "met": false },
  "block_new_long_reasons": []
}
```

| 字段 | 说明 |
|---|---|
| `phase` | 当日 **生效** 档位（规则档或手拨覆盖后）。 |
| `rule_phase` | 规则引擎算出的档位。 |
| `override_phase` / `override_reason` | 人手覆盖档位及理由；`null` 表示未覆盖。 |
| `cap_total_pct` / `cap_single_pct` | 总仓、单票上限比例（0~1）。 |
| `allow` / `forbid` | 页面「允许 / 禁止」动作文案。 |
| `expansion_allowed` | 是否允许扩张性开仓。 |
| `demoted` | 是否因宽度背离等被降档。 |
| `available=false` | 读数不足时预算不可用；`reason` 说明原因。 |

六档名称：`冰点观察`、`修复确认`、`升温扩张`、`高潮拥挤`、`过热防守`、`退潮杀伤`（`trade_budget.PHASES`）。

---

### A.5 `on_review_saved` {#a5-on_review_saved}

| 项 | 说明 |
|---|---|
| **中文作用** | 复盘 JSON **成功落盘** 后推送 **聚合包**：完整复盘 + 当次 metrics / verification / budget 快照，适合「一次落盘、一次外发」的集成场景。 |
| **HookPack 字段** | `on_review_saved` |
| **事件名** | `review.saved` |
| **触发时机** | `emit_after_review` 最后一步；受 `enable_review_saved` 控制。 |
| **对应页面** | [复盘看板](/agent/review) 全部内容（分析师报告、焦点、指标、验证条件、预算卡）；数据写入 `reviews/` 后与页面展示一致。 |
| **对应 API** | `POST /api/review/run`；读取侧 `GET /api/review/latest`、`GET /api/review/dates` |
| **回调签名** | `on_review_saved(ctx: HookContext, envelope: dict) -> None` |

**`envelope["payload"]` 结构**（内层 `$schema` = `review-saved/1.0.0`）：

```json
{
  "$schema": "https://vibe-astock.dev/schemas/hook/review-saved/1.0.0",
  "schema_version": "1.0.0",
  "date": "2026-01-02",
  "review": { },
  "metrics": { },
  "verification": { },
  "budget": { }
}
```

| 字段 | 说明 |
|---|---|
| `review` | 完整复盘 JSON，与 `review_store` 落盘字段一致（见下表）。 |
| `metrics` | 同 [A.2](#a2-on_metrics_snapshot) 的 payload（`scope=review`）。 |
| `verification` | 同 [A.3](#a3-on_verification_snapshot) 的 payload。 |
| `budget` | 同 [A.4](#a4-on_budget_snapshot) 的 payload；预算计算失败时为 `null`。 |

**`review` 主要字段**（与 [复盘看板](/agent/review) 展示对应）：

| 字段 | 页面区域 |
|---|---|
| `target_date` / `trade_date` | 日期选择器 |
| `warnings` | 降级警告条 |
| `focus` / `focus_md` | 明日焦点、方向结构 |
| `focus.verification_items` | AI 验证条件（只读） |
| `emotion_metrics` | 情绪指标卡（`EmotionMetricsPanel`） |
| `market_facts` | 市场事实面板（`MarketFactsPanel`） |
| `macro_sector` | 宏观板块段落 |
| `analysts` | 四位分析师 HTML 报告 |
| `reflection` | 上期预测回评 |

---

### A.6 `enable_review_saved` {#a6-enable_review_saved}

| 项 | 说明 |
|---|---|
| **中文作用** | 配置项：设为 `False` 时 **不** 派发 `review.saved`，但仍接收前面的分项快照（metrics / verification / budget）。 |
| **HookPack 字段** | `enable_review_saved`（默认 `True`） |
| **触发时机** | 无独立事件；仅影响 [A.5](#a5-on_review_saved) 是否执行。 |
| **对应页面** | 与 [A.5](#a5-on_review_saved) 相同；关闭后前端无变化，仅插件收包行为不同。 |
| **回调签名** | 无 |

---

## 附录 B：写入接口（插件 → 引擎）

---

### B.1 `import_portfolio` {#b1-import_portfolio}

| 项 | 说明 |
|---|---|
| **中文作用** | **全量覆盖** 本地持仓列表（VR `portfolio.json`），与截图导入确认写入同一校验规则。 |
| **调用方式** | `reg.import_portfolio(payload) -> ImportResult` |
| **对应页面** | [持仓与预算](/trade) — 持仓表、截图解析确认导入。 |
| **对应 API** | `POST /api/trade/screenshot/apply` |

**`payload` 结构**：

```json
{
  "replace": true,
  "holdings": [
    { "code": "600000", "shares": 100, "cost": 10.5 }
  ],
  "equity": 500000,
  "note": "收盘同步",
  "account_fields": { "cash_balance": 120000 }
}
```

| 字段 | 说明 |
|---|---|
| `replace` | 必须为 `true`（不支持增量合并）。 |
| `holdings[]` | `code`（6 位 A 股）、`shares>0`、`cost>0`；代码不可重复。 |
| `equity` / `note` / `account_fields` | 可选，与截图导入体相同。 |

落盘：`~/.vibe-research/portfolio.json`（受 `VR_DATA_DIR` 影响）。

---

### B.2 `import_account` {#b2-import_account}

| 项 | 说明 |
|---|---|
| **中文作用** | 更新账户权益、权益备注、命名账户栏位与交易常量（风险比例、日亏上限等）。 |
| **调用方式** | `reg.import_account(payload) -> ImportResult` |
| **对应页面** | [持仓与预算](/trade) — 权益输入、账户栏位、风险常量。 |
| **对应 API** | `POST /api/trade/account/equity`、`POST /api/trade/account/constants`、`POST /api/trade/account/snapshot` |

**`payload` 结构**：

```json
{
  "equity": 500000,
  "note": "收盘同步",
  "account_fields": {
    "cash_balance": 120000,
    "daily_pnl": -3500,
    "broker": "某券商"
  },
  "constants": {
    "risk_per_trade": 0.02,
    "daily_loss_limit": 0.03,
    "max_dd_soft": 0.08,
    "max_dd_hard": 0.15
  }
}
```

| 字段 | 说明 |
|---|---|
| `equity` | 可选；省略则仅更新栏位（需已有权益）。 |
| `account_fields` | 见 `trade_store._ACCOUNT_FIELD_KEYS`：`account_name`、`cash_balance`、`broker`、`daily_pnl` 等。 |
| 顶层同名键 | 与 `account_fields` 合并（如直接传 `cash_balance`）。 |
| `constants` | `risk_per_trade`、`daily_loss_limit`、`max_dd_soft`、`max_dd_hard`。 |

---

### B.3 `override_budget_phase` {#b3-override_budget_phase}

| 项 | 说明 |
|---|---|
| **中文作用** | 人手覆盖某日仓位档位，或清除覆盖恢复规则档。 |
| **调用方式** | `reg.override_budget_phase(date, phase, reason="")` |
| **对应页面** | [持仓与预算](/trade)、[复盘看板](/agent/review) 预算卡 — 手拨档位下拉。 |
| **对应 API** | `POST /api/trade/budget/override` |

| 参数 | 说明 |
|---|---|
| `date` | 交易日 `YYYY-MM-DD`。 |
| `phase` | `trade_budget.PHASES` 之一；传 `None` 清除覆盖。 |
| `reason` | 可选备注，写入 `override_reason`。 |

---

### B.4 `import_watchlist` {#b4-import_watchlist}

| 项 | 说明 |
|---|---|
| **中文作用** | **全量覆盖** 自选股列表，并同步盯盘池（`watchtower`）。 |
| **调用方式** | `reg.import_watchlist(payload) -> ImportResult` |
| **对应页面** | [自选股](/watchlist) |
| **对应 API** | `GET /api/watchlist`、`PUT /api/watchlist` |

**`payload` 结构**：

```json
{
  "replace": true,
  "codes": ["600000", "000001"]
}
```

| 字段 | 说明 |
|---|---|
| `replace` | 必须为 `true`。 |
| `codes` / `watchlist` | 最多 100 只 6 位 A 股代码；`codes: []` 清空列表。 |

落盘：`~/.vibe-research/watchlist.json`。

---

### B.5 `report_status` {#b5-report_status}

| 项 | 说明 |
|---|---|
| **中文作用** | 向引擎上报插件 **运行状态**（正常、提示、警告、错误），经 `GET /api/plugins` 转发至 [插件管理](/plugins) 列表展示。 |
| **调用方式** | `reg.report_status(level, message, detail=None)`；后台线程可用 `duanxian.plugin_status.set_status(plugin_id, ...)` |
| **对应页面** | [插件管理](/plugins) — 每条插件下的运行状态条。 |
| **对应 API** | `GET /api/plugins` 响应字段 `runtime_status` |

**`level` 取值**：

| level | 含义 |
|---|---|
| `ok` | 正常运行 |
| `info` | 一般提示（如等待外部服务） |
| `warn` | 可恢复异常（如同步失败但仍在重试） |
| `error` | 严重错误（需人工介入） |
| `off` | 停用（引擎对停用插件自动合成，插件无需上报） |

**`runtime_status` 结构**：

```json
{
  "level": "warn",
  "message": "同步异常：TimeoutError: 等待响应超时",
  "detail": "完整 traceback 或补充说明（可选）",
  "updated_at": "2026-08-23T11:30:00+08:00"
}
```

| 字段 | 说明 |
|---|---|
| `message` | 一行摘要，列表主文案 |
| `detail` | 可选详情（错误栈、连接参数等） |
| `updated_at` | 状态更新时间 |

**示例**（`on_register` 内绑定后上报）：

```python
def on_register(reg: HookRegistry) -> None:
    reg.report_status("info", "等待 ths-linker 连接…")
    try:
        connect_external()
        reg.report_status("ok", "已连接外部服务")
    except OSError as exc:
        reg.report_status("error", "连接失败", str(exc))
```

引擎在 **加载失败**、**on_register 失败**、**钩子回调失败** 时也会自动写入状态，无需插件重复上报。

---

## 附录 C：扩展指标

### C.1 `MetricProvider` {#c1-metricprovider}

| 项 | 说明 |
|---|---|
| **中文作用** | 向引擎注册自定义可验证指标：进入用户验证条件下拉、指标导出索引、AI 裁判指标池（可选）。 |
| **HookPack 字段** | `metric_providers: tuple[MetricProvider, ...]` |
| **触发时机** | 插件加载时校验并合并进 `verification.METRICS`；不单独派发事件。 |
| **对应页面** | [复盘看板](/agent/review) —「我自己的验证条件」指标下拉；AI 产出验证条件时的候选池。 |
| **对应 API** | `GET /api/verification/menu` |

**`MetricProvider` 字段**：

| 字段 | 说明 |
|---|---|
| `key` | 唯一标识；不可与内置 `verification.builtin_keys()` 冲突。 |
| `label` / `hint` | 下拉显示名与说明。 |
| `eps` | 核验容差。 |
| `getter(metrics, facts) -> float \| None` | `metrics` = `emotion_metrics`，`facts` = `market_facts`。 |
| `higher_is_hotter` | 数值升高是否更热。 |
| `unit` | 单位（如 `家`、`%`）。 |
| `scopes` | `review` / `live` / `both`；影响 `metric_index` 导出范围。 |
| `register_in` | 见下表。 |
| `path` | 可选 JSON 路径，写入 `metric_index.path`。 |

**`register_in` 取值**：

| 值 | 效果 |
|---|---|
| `verification_menu` | 出现在用户可选验证指标菜单 |
| `export_index` | 进入 `metrics.snapshot` 的 `metric_index`（须同时含 `verification_menu`） |
| `ai_pool` | 进入裁判 prompt 指标池；启动时 dry-run `getter`，算不出值则跳过 |

示例：

```python
from duanxian.hooks import MetricProvider, HookPack

def _my_signal(metrics: dict, facts: dict) -> float | None:
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

---

## 附录 D：公共类型

### D.1 `HookPack` {#d1-hookpack}

```python
@dataclass(frozen=True)
class HookPack:
    name: str
    version: str
    schema_bundle: str
    metric_providers: tuple[MetricProvider, ...] = ()
    on_register: Callable[[HookRegistry], None] | None = None
    on_enable: Callable[[HookRegistry], None] | None = None
    on_disable: Callable[[], None] | None = None
    on_metrics_snapshot: Callable[[HookContext, dict], None] | None = None
    on_budget_snapshot: Callable[[HookContext, dict], None] | None = None
    on_verification_snapshot: Callable[[HookContext, dict], None] | None = None
    on_review_saved: Callable[[HookContext, dict], None] | None = None
    enable_review_saved: bool = True
```

未实现的回调可省略（默认为 `None`）。各回调详表见 [附录 A](#附录-a-推送回调引擎--插件)。

---

### D.2 `HookContext` {#d2-hookcontext}

推送回调第一个参数，轻量上下文（无业务 payload）：

| 字段 | 说明 |
|---|---|
| `date` | 交易日 `YYYY-MM-DD` |
| `event` | 如 `metrics.snapshot`、`review.saved` |
| `emitted_at` | 发出时间（含时区） |
| `engine_version` | `duanxian.hook_schemas.ENGINE_VERSION`（当前 `0.1.3`） |
| `plugin_id` | 注册表中的 8 位 id |
| `plugin_name` / `plugin_version` | 来自 `PACK` |

---

### D.3 信封 `envelope` {#d3-envelope}

所有 push 回调的第二个参数，顶层结构统一：

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
