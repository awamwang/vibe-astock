# 插件生命周期

在注册、启用/停用、改代码不生效时阅读。权威：`doc/development/hook-lifecycle.md`。

## 注册表

- 路径：`~/.vibe-astock/plugins.json`
- CLI：`python -m duanxian.plugin_cli`（`list` / `register` / `enable` / `disable` / `uninstall`）
- `register` 校验文件可加载且含合法 `PACK`；**不复制**文件，路径须稳定
- `uninstall` 只删注册表项，不删 `.py`

## 加载规则

1. 仅 `enabled=true` 且文件仍存在的插件
2. 单插件 import 失败：警告并跳过，不阻断引擎
3. `on_enable` / `on_register`：有 `on_enable` 则只调它；否则调 `on_register`
4. 停用：`on_disable` → 从 RUNNER 移除 → **清除该插件消息源** → 卸载模块

## 变更何时生效

| 操作 | 已运行 server |
|------|----------------|
| enable / disable / uninstall | 即时（同进程） |
| register 且已启用 | 即时热加载 |
| 修改插件 `.py` | **需重启进程** |
| 独立 CLI 改注册表 | 不影响其他已运行 server |

## 交付时告诉用户

1. 注册命令与插件路径  
2. 改源码后重启 `server.py` / `main.py`  
3. 插件管理页可看 `report_status` 与加载错误  
4. 引擎会在 `error` / 未加载时按指数退避自动热重启（见 hook-lifecycle「自动检测与重启」）
