"""最小可注册钩子插件模板 —— 复制后改 name 与能力。"""

from __future__ import annotations

from duanxian.hooks import HookPack, HookRegistry

_REG: HookRegistry | None = None
_PID: str | None = None


def on_enable(reg: HookRegistry) -> None:
    """进程加载或管理页启用时调用；可登记消息源、启动后台任务。"""
    global _REG, _PID
    _REG, _PID = reg, reg.plugin_id
    # reg.register_message_source("my_feed", "我的快讯")
    reg.report_status("ok", "已启用")


def on_disable() -> None:
    """停用时释放连接与后台线程；消息源由引擎自动注销。"""
    global _REG, _PID
    _REG = None
    _PID = None


PACK = HookPack(
    name="minimal-example",
    version="1.0.0",
    schema_bundle="minimal-example/1.0.0",
    on_enable=on_enable,
    on_disable=on_disable,
)
