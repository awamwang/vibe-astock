"""从插件目录 .env 与进程环境读取飞书凭证和资源标识。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = _PLUGIN_DIR / ".env.example"
ENV_FILE = _PLUGIN_DIR / ".env"

_RECEIVE_ID_TYPES = frozenset({"open_id", "user_id", "union_id", "email", "chat_id"})
_DOMAINS = frozenset({"feishu", "lark"})

# (变量名, 空值时提示给用户的说明)
_REQUIRED: tuple[tuple[str, str], ...] = (
    ("LARK_APP_ID", "飞书应用 App ID"),
    ("LARK_APP_SECRET", "飞书应用 App Secret"),
    ("LARK_DRIVE_FOLDER_TOKEN", "云空间文件夹 token"),
    ("LARK_BITABLE_APP_TOKEN", "多维表格 app_token"),
    ("LARK_BITABLE_TABLE_ID", "多维表格数据表 table_id"),
    ("LARK_SPREADSHEET_TOKEN", "电子表格 spreadsheet token"),
    ("LARK_SHEET_ID", "电子表格工作表 sheet id"),
    ("LARK_IM_RECEIVE_ID", "消息接收方 ID"),
)


@dataclass(frozen=True)
class LarkConfig:
    """启用插件所需的应用凭证和四项资源标识。"""

    app_id: str
    app_secret: str
    domain: str
    drive_folder_token: str
    bitable_app_token: str
    bitable_table_id: str
    spreadsheet_token: str
    sheet_id: str
    im_receive_id_type: str
    im_receive_id: str


def load_env_file(path: Path) -> None:
    """把 KEY=VALUE 写入尚未设置的环境变量。不覆盖进程里已有的值。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def load_config(env_file: Path | None = None) -> LarkConfig:
    """读取配置。缺必填项时列出变量名，要求先填 .env。"""
    load_env_file(env_file or ENV_FILE)
    missing = [f"{key}（{label}）" for key, label in _REQUIRED if not os.environ.get(key, "").strip()]
    if missing:
        lines = "\n".join(f"- {item}" for item in missing)
        raise ConfigError(
            "飞书插件配置未填完。请把 plugins/lark-stock/.env.example 复制为 "
            f"plugins/lark-stock/.env 并填写：\n{lines}"
        )

    domain = os.environ.get("LARK_DOMAIN", "feishu").strip().lower() or "feishu"
    if domain not in _DOMAINS:
        raise ConfigError("LARK_DOMAIN 只能是 feishu 或 lark")

    receive_id_type = os.environ.get("LARK_IM_RECEIVE_ID_TYPE", "chat_id").strip() or "chat_id"
    if receive_id_type not in _RECEIVE_ID_TYPES:
        allowed = "、".join(sorted(_RECEIVE_ID_TYPES))
        raise ConfigError(f"LARK_IM_RECEIVE_ID_TYPE 只能是 {allowed}")

    return LarkConfig(
        app_id=os.environ["LARK_APP_ID"].strip(),
        app_secret=os.environ["LARK_APP_SECRET"].strip(),
        domain=domain,
        drive_folder_token=os.environ["LARK_DRIVE_FOLDER_TOKEN"].strip(),
        bitable_app_token=os.environ["LARK_BITABLE_APP_TOKEN"].strip(),
        bitable_table_id=os.environ["LARK_BITABLE_TABLE_ID"].strip(),
        spreadsheet_token=os.environ["LARK_SPREADSHEET_TOKEN"].strip(),
        sheet_id=os.environ["LARK_SHEET_ID"].strip(),
        im_receive_id_type=receive_id_type,
        im_receive_id=os.environ["LARK_IM_RECEIVE_ID"].strip(),
    )
