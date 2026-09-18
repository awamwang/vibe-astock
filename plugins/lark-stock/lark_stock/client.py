"""构造飞书官方 Python SDK 客户端。"""

from __future__ import annotations

from typing import Any

from .config import LarkConfig


def build_client(config: LarkConfig) -> Any:
    """用应用凭证创建自建应用客户端。此时不发起网络请求。"""
    import lark_oapi as lark

    domain = lark.LARK_DOMAIN if config.domain == "lark" else lark.FEISHU_DOMAIN
    return (
        lark.Client.builder()
        .app_id(config.app_id)
        .app_secret(config.app_secret)
        .domain(domain)
        .log_level(lark.LogLevel.INFO)
        .build()
    )
