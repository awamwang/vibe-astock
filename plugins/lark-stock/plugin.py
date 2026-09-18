"""飞书插件入口。

依赖：pip install -r plugins/lark-stock/requirements.txt
配置：在插件管理页展开「配置」填写，或把同目录 .env.example 复制为 .env。
启用只需 App ID 与 App Secret；云空间、表格、消息接收方可后补。
管理页保存的值在用户目录 plugins.plugin-env，已填写项优先于 .env。
启用后登记页面，地址为 /plugin/{插件 id}，插件名 /plugin/lark-stock 同样可打开。
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_REQ_FILE = _ROOT / "requirements.txt"

try:
    import lark_oapi  # noqa: F401
except ImportError as exc:
    raise ImportError(
        f"lark-stock 插件需要 lark-oapi：pip install -r {_REQ_FILE}"
    ) from exc

from duanxian.hooks import HookPack, HookRegistry
from lark_stock.config import ENV_FIELDS, load_config
from lark_stock.errors import ConfigError
from lark_stock.page import handle_send, handle_today, handle_push, render_home
from lark_stock.service import LarkStock
from lark_stock.settled_push import SettledPushPoller

_service: LarkStock | None = None
_registry: HookRegistry | None = None
_poller: SettledPushPoller | None = None


def get_service() -> LarkStock:
    """返回已启用的飞书客户端。未启用或配置未通过时不可用。"""
    if _service is None:
        raise RuntimeError("飞书插件尚未启用")
    return _service


def on_enable(reg: HookRegistry) -> None:
    """校验应用凭证并建好客户端。资源标识未填不影响启用。"""
    global _service, _registry, _poller
    try:
        config = load_config()
    except ConfigError as exc:
        raise RuntimeError(str(exc)) from exc
    _service = LarkStock(config)
    _registry = reg
    plugin_id = reg.plugin_id or "lark-stock"
    home_url = f"/plugin/{plugin_id}"

    def _open_home() -> str:
        href = html.escape(home_url, quote=True)
        return (
            "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"/>"
            f"<p>请从<a href=\"{href}\">插件页面</a>操作。</p>"
        )

    def home() -> str:
        return render_home(get_service().config, plugin_id)

    def _live() -> dict:
        return (_registry or reg).get_live_snapshot()

    def today(request) -> str | dict:
        if (request.method or "GET").upper() == "GET":
            return _open_home()
        return handle_today(get_service(), plugin_id)

    def push(request) -> str | dict:
        if (request.method or "GET").upper() == "GET":
            return _open_home()
        return handle_push(get_service(), plugin_id, fetch_live=_live)

    def send(request) -> str | dict:
        if (request.method or "GET").upper() == "GET":
            return _open_home()
        return handle_send(get_service(), request, plugin_id)

    reg.register_route("", "飞书短线与消息", handler=home)
    reg.register_route("today", "拉取今日短线", handler=today, methods=("GET", "POST"), visible=False)
    reg.register_route("push", "推送今日短线盘面", handler=push, methods=("GET", "POST"), visible=False)
    reg.register_route("send", "发送消息", handler=send, methods=("GET", "POST"), visible=False)

    if _poller is not None:
        _poller.stop()
    _poller = SettledPushPoller(
        service=_service,
        plugin_id=plugin_id,
        fetch_live=_live,
        registry=reg,
    )
    _poller.start()
    reg.report_status("ok", "飞书客户端已就绪，收盘后将自动推送定稿短线")


def on_disable() -> None:
    global _service, _registry, _poller
    if _poller is not None:
        _poller.stop()
        _poller = None
    _service = None
    _registry = None


PACK = HookPack(
    name="lark-stock",
    version="0.1.0",
    schema_bundle="lark-stock/0.1.0",
    env_fields=ENV_FIELDS,
    on_enable=on_enable,
    on_disable=on_disable,
)
