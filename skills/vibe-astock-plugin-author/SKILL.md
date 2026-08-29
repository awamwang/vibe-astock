---
name: vibe-astock-plugin-author
description: "编写、改造或审查 vibe-astock 钩子插件（HookPack / HookRegistry）：脚手架、CLI 注册、写入接口（持仓/账户/自选/当前股/消息源推送）、引擎 push 回调、生命周期与并发约定。在用户要写插件、注册消息源、push_messages、on_enable、桥接外部行情/同花顺时使用。不用于从截图解析持仓 JSON（用 portfolio-holding-parse）。"
---

# vibe-astock 插件写作

按仓库已发布契约写可加载的钩子插件。事实来源以仓库文档与源码为准；本技能给出稳定流程与分支索引，细节冲突时以 `doc/development/plugin-development.md` 与 `duanxian/hooks.py` 为准。

## 何时用

- 新建/改写导出 `PACK = HookPack(...)` 的插件 `.py`
- 接入 `HookRegistry` 写入：持仓、账户、自选、当前股、**消息源注册与标准格式推送**
- 订阅复盘/预算/验证等引擎 → 插件回调
- 启用/停用、CLI 注册、多线程推送约定

## 何时不用

- 仅把持仓截图解析成导入 JSON → 用 `portfolio-holding-parse`
- 改引擎内核或消息库 schema（除非任务明确要求改系统侧）

## 必读契约（按需加载）

| 任务 | 读 |
|------|-----|
| 脚手架 + 注册 CLI + 完成检查 | 下文流程（足够） |
| 写入 API 字段与示例 | `references/write-apis.md` |
| 消息源注册 + `message-push/1.0.0` | `references/message-source.md` |
| 引擎 push 回调与信封 | `references/push-callbacks.md` |
| 启用/停用/热加载 | `references/lifecycle.md` |
| WS/后台线程与 `bind_plugin` | `references/concurrency.md` |
| 可复制最小插件 | `templates/minimal_plugin.py` |

深度附录（勿整篇复制进插件）：`doc/development/plugin-development.md`、`doc/development/hook-lifecycle.md`、`doc/development/lock-safety.md`。仓库示例：`plugins/vibe-ths-linker/plugin.py`。

## 决策树

```text
用户要做什么？
├── 新建插件文件
│   └── 用 templates/minimal_plugin.py → 按能力加回调/写入 → CLI register
├── 只推消息进消息分析
│   └── on_enable 登记源 → 读 message-source.md → push_messages
├── 同步持仓/账户/自选/当前股
│   └── 读 write-apis.md；异步路径再读 concurrency.md
├── 接收复盘/预算快照
│   └── 读 push-callbacks.md
└── 排查加载/停用/改代码不生效
    └── 读 lifecycle.md
```

## 写作流程

1. **定能力边界**：列出需要的写入方法与 push 回调；不实现的能力不要占位空函数。
2. **落盘插件文件**：建议用户目录 `~/.vibe-astock/plugins/<name>.py`，或仓库 `plugins/<name>/`（不随默认安装自动启用）。文件必须导出合法 `PACK`。
3. **实现激活钩子**：优先 `on_enable(reg)`（与 `on_register` 二选一即可；两者都有时引擎只调 `on_enable`）。在此 `register_message_source`、启动后台任务、记下 `pid = reg.plugin_id`。
4. **实现 `on_disable`**：停线程、关连接；消息源由引擎在停用时 `unregister_plugin`，插件无需手清注册表。
5. **异步写入**：后台 worker 先 `reg.bind_plugin(pid)` 再调 Registry；**禁止**在 WebSocket/SSE 读线程里同步 `report_current_stock` / `push_messages` / 重 I/O。细节见 `references/concurrency.md`。
6. **注册并启用**：
   ```bash
   python -m duanxian.plugin_cli register <path>
   python -m duanxian.plugin_cli enable <id|name>
   ```
   改 `.py` 源码后需**重启 server**；仅 enable/disable 可即时生效。
7. **完成检查**（全部满足才交付）：
   - [ ] 存在 `PACK = HookPack(...)`，`name`/`version`/`schema_bundle` 已填
   - [ ] 用到的每条写入/回调在对应 reference 中有字段依据
   - [ ] 消息源未占用保留 id：`manual` / `article` / `calendar` / `cls_telegraph` / `xgb_msgs`
   - [ ] 推送消息已转为系统标准格式（引擎不做厂商解析）
   - [ ] 异步路径有入队 + `bind_plugin`；读线程无同步重操作
   - [ ] 已说明 CLI 注册命令与「改代码需重启」

## 最小骨架

```python
from duanxian.hooks import HookPack, HookRegistry

def on_enable(reg: HookRegistry) -> None:
    reg.report_status("ok", "已启用")

def on_disable() -> None:
    pass

PACK = HookPack(
    name="my-plugin",
    version="1.0.0",
    schema_bundle="my-plugin/1.0.0",
    on_enable=on_enable,
    on_disable=on_disable,
)
```

完整可运行模板见 `templates/minimal_plugin.py`。

## 设计约束（勿依赖）

- 插件与引擎**同权同进程**，不是安全沙箱；只装可信代码。
- 系统**不轮询**插件消息源；插件主动 `push_messages`。
- 钩子异常只记日志，不阻断复盘主流程；`on_enable` 抛 `RuntimeError` 时界面可展示短文案。
