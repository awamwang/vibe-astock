# 引擎 push 回调（引擎 → 插件）

在插件需要接收复盘/预算/验证快照时阅读。权威：`plugin-development.md` 附录 A；派发：`HookRunner`。

| 回调 | 事件 | 典型触发 |
|------|------|----------|
| `on_metrics_snapshot` | `metrics.snapshot` | 复盘保存后 |
| `on_verification_snapshot` | `verification.snapshot` | 复盘保存后；用户保存验证条件 |
| `on_budget_snapshot` | `budget.snapshot` | `trade_store.refresh(emit_hooks=True)`；复盘保存后有预算时 |
| `on_review_saved` | `review.saved` | 复盘保存后聚合包（可用 `enable_review_saved=False` 关闭） |

签名：`callback(ctx: HookContext, envelope: dict) -> None`。

信封顶层含 `$schema`（envelope）、`event`、`date`、`emitted_at`、`engine_version`、`plugin`、`payload`。  
`payload` 内各自有 `metrics-snapshot` / `verification-snapshot` / `budget-snapshot` / `review-saved` 的 `$schema`（见 `duanxian/hook_schemas.py`）。

## 复盘路径顺序（每插件）

1. metrics.snapshot（scope=review）  
2. verification.snapshot  
3. budget.snapshot（有 budget 时）  
4. review.saved（若未关闭）

复盘主路径对 `refresh(..., emit_hooks=False)`，由 `emit_after_review` 统一发 budget，避免 double-fire。

## MetricProvider

扩展验证指标时在 `HookPack.metric_providers` 注册；`key` 勿与内置冲突。字段与 `register_in` 见文档附录 C。加载时校验失败会跳过该项并打日志，不阻断插件其余能力。

## 错误隔离

单插件回调抛错只打印警告，不影响其他插件与复盘事务。
