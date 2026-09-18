"""从插件目录 .env 与进程环境读取飞书凭证和资源标识。

启用只要求应用 App ID 与 App Secret，其余资源标识可后补。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from duanxian.hooks import PluginEnvField

from .errors import ConfigError

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = _PLUGIN_DIR / ".env.example"
ENV_FILE = _PLUGIN_DIR / ".env"

_RECEIVE_ID_TYPES = frozenset({"open_id", "user_id", "union_id", "email", "chat_id"})
_DOMAINS = frozenset({"feishu", "lark"})

# (变量名, 空值时提示给用户的说明)。资源标识未填不影响启用。
_REQUIRED: tuple[tuple[str, str], ...] = (
    ("LARK_APP_ID", "飞书应用 App ID"),
    ("LARK_APP_SECRET", "飞书应用 App Secret"),
)

@dataclass(frozen=True)
class BitableColumn:
    """短线盘面一个指标对应的多维表格列名。"""

    key: str
    label: str
    hint: str = "写入多维表格的列名，留空则用页面上的中文名称"


# 短线盘面上半部分（标签页以上）的卡片，顺序与页面一致。
# 上证/A股量能盘中会显示成「预测量能」，仍是同一列。
DUANXIAN_BITABLE_COLUMNS: tuple[BitableColumn, ...] = (
    BitableColumn("DUANXIAN_DATE_BITABLE_KEY_NAME", "日期"), 
    BitableColumn("DUANXIAN_TEMPERATURE_BITABLE_KEY_NAME", "情绪温度"), 
    BitableColumn("DUANXIAN_BREADTH_BITABLE_KEY_NAME", "大盘宽度"),
    BitableColumn("DUANXIAN_SPECULATION_BITABLE_KEY_NAME", "题材投机"),
    BitableColumn("DUANXIAN_UP_BITABLE_KEY_NAME", "上涨数"),
    BitableColumn("DUANXIAN_DOWN_BITABLE_KEY_NAME", "下跌数"),
    BitableColumn("DUANXIAN_FLAT_BITABLE_KEY_NAME", "平盘"),
    BitableColumn("DUANXIAN_ACTIVE_BITABLE_KEY_NAME", "活跃度"),
    BitableColumn(
        "DUANXIAN_SH_VOLUME_BITABLE_KEY_NAME",
        "上证量能",
        "盘中界面为「上证预测量能」，与定稿后的「上证量能」同一列",
    ),
    BitableColumn(
        "DUANXIAN_A_VOLUME_BITABLE_KEY_NAME",
        "A股量能",
        "盘中界面为「A股预测量能」，与定稿后的「A股量能」同一列",
    ),
    BitableColumn("DUANXIAN_MAIN_INFLOW_BITABLE_KEY_NAME", "主力净流入"),
    BitableColumn("DUANXIAN_VOL_RATIO_5D_BITABLE_KEY_NAME", "5日量比"),
    BitableColumn("DUANXIAN_VOL_RATIO_20D_BITABLE_KEY_NAME", "20日量比"),
    BitableColumn("DUANXIAN_EMOTION_SCORE_BITABLE_KEY_NAME", "情绪分"),
    BitableColumn("DUANXIAN_PHASE_BITABLE_KEY_NAME", "阶段"),
    BitableColumn("DUANXIAN_LIMIT_UP_BITABLE_KEY_NAME", "涨停数"),
    BitableColumn("DUANXIAN_LIMIT_DOWN_BITABLE_KEY_NAME", "跌停数"),
    BitableColumn("DUANXIAN_LEADER_BITABLE_KEY_NAME", "龙头"),
    BitableColumn("DUANXIAN_THEMES_BITABLE_KEY_NAME", "主线题材"),
    BitableColumn("DUANXIAN_OPEN_SUCCESS_BITABLE_KEY_NAME", "打板成功率"),
    BitableColumn("DUANXIAN_ZT_PREMIUM_BITABLE_KEY_NAME", "涨停溢价"),
    BitableColumn("DUANXIAN_LIANBAN_PREMIUM_BITABLE_KEY_NAME", "连板溢价"),
    BitableColumn("DUANXIAN_PROMOTION_BITABLE_KEY_NAME", "晋级率"),
    BitableColumn("DUANXIAN_BROKEN_RATE_BITABLE_KEY_NAME", "炸板率"),
    BitableColumn("DUANXIAN_MAX_BOARDS_BITABLE_KEY_NAME", "连板高度"),
    BitableColumn("DUANXIAN_LIANBAN_COUNT_BITABLE_KEY_NAME", "连板数"),
    BitableColumn("DUANXIAN_ZT_DEEP_LOSS_BITABLE_KEY_NAME", "昨涨停跌超5%"),
    BitableColumn("DUANXIAN_BROKEN_COUNT_BITABLE_KEY_NAME", "炸板家数"),
    BitableColumn("DUANXIAN_RESONANCE_BITABLE_KEY_NAME", "打板情绪共振"),
)


def _column_fields() -> tuple[PluginEnvField, ...]:
    return tuple(
        PluginEnvField(col.key, col.label, col.hint, default=col.label)
        for col in DUANXIAN_BITABLE_COLUMNS
    )


ENV_FIELDS: tuple[PluginEnvField, ...] = (
    PluginEnvField("LARK_APP_ID", "应用 App ID", "飞书开放平台 → 应用 → 凭证与基础信息"),
    PluginEnvField("LARK_APP_SECRET", "应用 App Secret", secret=True),
    PluginEnvField("LARK_DOMAIN", "开放平台域名", "feishu（国内）或 lark（国际）", default="feishu"),
    PluginEnvField(
        "LARK_DRIVE_FOLDER_TOKEN",
        "云空间文件夹 token",
        "打开目标文件夹，链接里 /folder/ 后面那一段",
        secret=True,
    ),
    PluginEnvField(
        "LARK_BITABLE_APP_TOKEN",
        "多维表格 app_token",
        "链接 /base/ 后面",
        secret=True,
    ),
    PluginEnvField(
        "LARK_BITABLE_TABLE_ID",
        "多维表格 table_id",
        "链接 table= 后面",
        secret=True,
    ),
    PluginEnvField(
        "DUANXIAN_BITABLE_APP_TOKEN",
        "短线盘面多维表格 app_token",
        "短线盘面指标写入的表，链接 /base/ 后面",
        secret=True,
    ),
    PluginEnvField(
        "DUANXIAN_BITABLE_TABLE_ID",
        "短线盘面多维表格 table_id",
        "短线盘面指标写入的数据表，链接 table= 后面",
        secret=True,
    ),
    *_column_fields(),
    PluginEnvField(
        "LARK_SPREADSHEET_TOKEN",
        "电子表格 token",
        "链接 /sheets/ 后面",
        secret=True,
    ),
    PluginEnvField("LARK_SHEET_ID", "工作表 sheet id", "链接 sheet= 后面", secret=True),
    PluginEnvField(
        "LARK_IM_RECEIVE_ID_TYPE",
        "消息接收方类型",
        "chat_id / open_id / user_id / union_id / email",
        default="chat_id",
    ),
    PluginEnvField("LARK_IM_RECEIVE_ID", "消息接收方 ID", secret=True),
)


@dataclass(frozen=True)
class LarkConfig:
    """应用凭证，以及可后补的云空间、表格和消息接收方。未填的资源字段为空字符串。"""

    app_id: str
    app_secret: str
    domain: str
    drive_folder_token: str
    bitable_app_token: str
    bitable_table_id: str
    duanxian_bitable_app_token: str
    duanxian_bitable_table_id: str
    duanxian_columns: dict[str, str]
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


def _env(key: str) -> str:
    return os.environ.get(key, "").strip()


def duanxian_table_ids(config: LarkConfig) -> tuple[str, str]:
    """短线盘面写入用的多维表格。未单独配置时回落到通用表。"""
    app = (config.duanxian_bitable_app_token or config.bitable_app_token or "").strip()
    table = (config.duanxian_bitable_table_id or config.bitable_table_id or "").strip()
    return app, table


def load_config(env_file: Path | None = None) -> LarkConfig:
    """读取配置。只缺 App ID 或 App Secret 时阻止启用，其余资源标识可留空。"""
    load_env_file(env_file or ENV_FILE)
    missing = [f"{key}（{label}）" for key, label in _REQUIRED if not _env(key)]
    if missing:
        lines = "\n".join(f"- {item}" for item in missing)
        raise ConfigError(
            "飞书插件缺少应用凭证。请把 plugins/lark-stock/.env.example 复制为 "
            f"plugins/lark-stock/.env 并填写：\n{lines}"
        )

    domain = _env("LARK_DOMAIN").lower() or "feishu"
    if domain not in _DOMAINS:
        raise ConfigError("LARK_DOMAIN 只能是 feishu 或 lark")

    receive_id_type = _env("LARK_IM_RECEIVE_ID_TYPE") or "chat_id"
    if receive_id_type not in _RECEIVE_ID_TYPES:
        allowed = "、".join(sorted(_RECEIVE_ID_TYPES))
        raise ConfigError(f"LARK_IM_RECEIVE_ID_TYPE 只能是 {allowed}")

    return LarkConfig(
        app_id=_env("LARK_APP_ID"),
        app_secret=_env("LARK_APP_SECRET"),
        domain=domain,
        drive_folder_token=_env("LARK_DRIVE_FOLDER_TOKEN"),
        bitable_app_token=_env("LARK_BITABLE_APP_TOKEN"),
        bitable_table_id=_env("LARK_BITABLE_TABLE_ID"),
        duanxian_bitable_app_token=_env("DUANXIAN_BITABLE_APP_TOKEN"),
        duanxian_bitable_table_id=_env("DUANXIAN_BITABLE_TABLE_ID"),
        duanxian_columns={
            col.key: _env(col.key) or col.label
            for col in DUANXIAN_BITABLE_COLUMNS
        },
        spreadsheet_token=_env("LARK_SPREADSHEET_TOKEN"),
        sheet_id=_env("LARK_SHEET_ID"),
        im_receive_id_type=receive_id_type,
        im_receive_id=_env("LARK_IM_RECEIVE_ID"),
    )
