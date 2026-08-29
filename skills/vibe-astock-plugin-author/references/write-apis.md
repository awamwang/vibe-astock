# 写入接口（插件 → 引擎）

在需要调用 `HookRegistry` 写入方法时阅读；按用户能力只取相关小节。权威细节：`doc/development/plugin-development.md` 附录 B；实现：`duanxian/hooks.py`。

调用前须已 `bind_plugin`（`on_enable` 内自动绑定；后台线程须自行 `reg.bind_plugin(pid)`）。

| 方法 | 作用 | 要点 |
|------|------|------|
| `import_portfolio` | 全量覆盖持仓 | `replace` 必须为 `true`；`holdings[]`：`code` 6 位、`shares>0`、`cost>0` |
| `import_account` | 权益/栏位/风险常量 | `equity` 可选；`account_fields` / `constants` |
| `override_budget_phase` | 覆盖某日仓位档 | `date`、`phase`（或清除） |
| `import_watchlist` | 自选股 | `replace=true` 全量，或 `merge=true` 按来源合并 |
| `report_status` | 插件管理页状态 | `level`：`ok`/`info`/`error` 等；`message`、`detail` |
| `report_current_stock` | 当前看盘股 | `code` 必填 6 位；未变返回 `detail=unchanged` |
| `register_message_source` | 登记消息源 | 见 `message-source.md` |
| `push_messages` | 标准格式推送消息 | 见 `message-source.md` |

返回多为 `ImportResult(ok, kind, detail)`。

## `import_portfolio` 形状

```json
{
  "replace": true,
  "holdings": [{"code": "600000", "shares": 100, "cost": 10.5}],
  "equity": 500000,
  "note": "同步",
  "account_fields": {"cash_balance": 120000}
}
```

## `import_watchlist` 形状

```json
{"replace": true, "codes": ["600000", "000001"], "source": "插件：示例"}
```

或 `{"merge": true, "codes": ["600000"], "source": "插件：示例"}`。

## `report_current_stock` 形状

```json
{"code": "600000", "source": "push", "prev": "000001", "symbol": "600000.SH"}
```

读线程禁止同步调用；先入队。见 `concurrency.md`。
