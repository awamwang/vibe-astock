"""飞书四项能力的统一入口。"""

from __future__ import annotations

from .bitable import BitableStore
from .client import build_client
from .config import LarkConfig, duanxian_table_ids
from .drive import DriveStore
from .messenger import Messenger
from .sheets import SheetStore


class LarkStock:
    """持有一个客户端，分别操作云空间、多维表格、电子表格和消息。"""

    def __init__(self, config: LarkConfig) -> None:
        client = build_client(config)
        self.config = config
        self.drive = DriveStore(client, config)
        self.bitable = BitableStore(client, config)
        duanxian_app, duanxian_table = duanxian_table_ids(config)
        self.duanxian_bitable = BitableStore(
            client,
            config,
            app_token=duanxian_app,
            table_id=duanxian_table,
        )
        self.sheets = SheetStore(client, config)
        self.messenger = Messenger(client, config)
