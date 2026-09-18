"""飞书插件配置：只有应用凭证是启用必填项。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "lark-stock"
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from lark_stock.config import load_config  # noqa: E402
from lark_stock.errors import ConfigError  # noqa: E402

_OPTIONAL_KEYS = (
    "LARK_DOMAIN",
    "LARK_DRIVE_FOLDER_TOKEN",
    "LARK_BITABLE_APP_TOKEN",
    "LARK_BITABLE_TABLE_ID",
    "DUANXIAN_BITABLE_APP_TOKEN",
    "DUANXIAN_BITABLE_TABLE_ID",
    "LARK_SPREADSHEET_TOKEN",
    "LARK_SHEET_ID",
    "LARK_IM_RECEIVE_ID_TYPE",
    "LARK_IM_RECEIVE_ID",
)


@pytest.fixture
def isolated_env(monkeypatch):
    for key in ("LARK_APP_ID", "LARK_APP_SECRET", *_OPTIONAL_KEYS):
        monkeypatch.delenv(key, raising=False)


def test_only_app_credentials_are_required(isolated_env, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LARK_APP_ID=cli_test\nLARK_APP_SECRET=secret\n", encoding="utf-8")

    config = load_config(env_file)

    assert config.app_id == "cli_test"
    assert config.app_secret == "secret"
    assert config.domain == "feishu"
    assert config.drive_folder_token == ""
    assert config.bitable_app_token == ""
    assert config.bitable_table_id == ""
    assert config.spreadsheet_token == ""
    assert config.sheet_id == ""
    assert config.im_receive_id_type == "chat_id"
    assert config.im_receive_id == ""


def test_duanxian_table_falls_back_to_generic(isolated_env, tmp_path):
    from lark_stock.config import duanxian_table_ids

    env_file = tmp_path / ".env"
    env_file.write_text(
        "LARK_APP_ID=cli_test\nLARK_APP_SECRET=secret\n"
        "LARK_BITABLE_APP_TOKEN=app\nLARK_BITABLE_TABLE_ID=tbl\n",
        encoding="utf-8",
    )
    config = load_config(env_file)
    assert duanxian_table_ids(config) == ("app", "tbl")


def test_missing_app_secret_blocks_enable(isolated_env, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LARK_APP_ID=cli_test\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="LARK_APP_SECRET"):
        load_config(env_file)
