# 消息源注册与标准格式推送

在插件要把外部消息接入「消息分析」时阅读。权威：`plugin-development.md` B.7/B.8；实现：`duanxian/message_sources.py`、`HookRegistry.push_messages`。

## 职责划分

| 角色 | 职责 |
|------|------|
| 系统 | 规定标准格式、校验归属、入库（raw / 可选 analyzed）、`list_sources` 合并展示 |
| 插件 | 注册 `source_id`、把外部消息串**转换成标准格式**后主动推送 |

系统**不轮询**插件；停用插件时引擎清除该插件登记的源。

## 注册

```python
def on_enable(reg: HookRegistry) -> None:
    global _REG, _PID
    _REG, _PID = reg, reg.plugin_id
    reg.register_message_source("my_feed", "我的快讯")
```

保留 id（不可注册）：`manual`、`article`、`calendar`、`cls_telegraph`、`xgb_msgs`。  
他插件已占用的 `source_id` 会 `ValueError`。同插件重复注册可更新 `label`。

展示：`GET /api/messages/sources` 中 `adapter_type=plugin`（进程内，不落 SQLite `message_source` 表）。

## 推送 payload（`$schema` = message-push/1.0.0）

```json
{
  "$schema": "https://vibe-astock.dev/schemas/hook/message-push/1.0.0",
  "source_id": "my_feed",
  "auto_analyze": false,
  "messages": [
    {
      "content": "必填正文",
      "title": "",
      "keywords": [],
      "url": "",
      "marks": [],
      "external_ref": "可选幂等键",
      "produced_at": "YYYY-MM-DD HH:MM:SS",
      "effective_mode": "immediate",
      "effective_at": null,
      "targets": [{"kind": "stock", "code": "600000", "name": "浦发银行"}],
      "summary": "仅 auto_analyze 时写入 analyzed",
      "detail": "",
      "impact_level": "medium",
      "meta": {}
    }
  ]
}
```

- 默认只 `insert_raw_batch`；`auto_analyze=true` 时对**新插入**的 raw 调 `upsert_analyzed_from_raw`。
- `external_ref` / `content_hash` 去重与手动入库一致；二次推同一 `external_ref` 不重复插。
- 返回 `detail` 形如 `inserted=N analyzed=M`。
- `$schema` 可省略（按 1.0.0）；错误 schema 拒绝。

## 异步推送

```python
_REG.bind_plugin(_PID)
_REG.push_messages({
    "source_id": "my_feed",
    "auto_analyze": True,
    "messages": [{"content": "某条快讯", "external_ref": "ext-1", "impact_level": "high"}],
})
```

读线程只入队；worker 再 `bind_plugin` + `push_messages`。见 `concurrency.md`。
