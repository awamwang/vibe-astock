"""飞书插件入口。

依赖：pip install -r plugins/lark-stock/requirements.txt
配置：把 plugins/lark-stock/.env.example 复制为 .env 并填写。
"""

from __future__ import annotations

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
from lark_stock.config import load_config
from lark_stock.errors import ConfigError
from lark_stock.service import LarkStock

_service: LarkStock | None = None


def get_service() -> LarkStock:
    """返回已启用的飞书客户端。未启用或配置未通过时不可用。"""
    if _service is None:
        raise RuntimeError("飞书插件尚未启用")
    return _service


def on_enable(reg: HookRegistry) -> None:
    """校验 .env 并建好客户端。缺配置时把要填的变量名报给插件状态。"""
    global _service
    try:
        config = load_config()
    except ConfigError as exc:
        raise RuntimeError(str(exc)) from exc
    _service = LarkStock(config)
    reg.report_status("ok", "飞书客户端已就绪")


def on_disable() -> None:
    global _service
    _service = None


PACK = HookPack(
    name="lark-stock",
    version="0.1.0",
    schema_bundle="lark-stock/0.1.0",
    on_enable=on_enable,
    on_disable=on_disable,
)
