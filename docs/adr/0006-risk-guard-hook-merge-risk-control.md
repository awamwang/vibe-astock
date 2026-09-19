# 账户风控闸用独立钩子，再并入既有风控 WebSocket

账户风控闸（单只持仓亏损、总仓位亏损、连亏天数、亏损持仓累积、峰值回撤）评估完成后发独立事件 `risk.guard`（`on_risk_guard`），不塞进仓位预算快照。ths-linker 收到后入队，把 `global_no_buy` / `reason` / `meta` 并进已有的 `risk_control` update；定时同步也必须带上这三件套，以免把硬闸冲掉。硬闸解除时同样派发 `global_no_buy: false`。本期不自动下单。

**Considered Options**
- 把禁止买入塞进 `budget.snapshot`：预算刷新与账户/持仓更新不是同一节奏，也会让未订阅预算的联动插件漏掉硬闸。
- 新开一条 WebSocket 类型：联动工具已有 `risk_control` get/update，再拆通道会双写、难对账。
- 在 `import_portfolio` 回调里同步打 WS：会与持仓写入同栈嵌套，违反锁安全（须入队）。
