"""Send one test Lark/Feishu IM message using plugins/lark-stock/.env."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "lark-stock"
sys.path.insert(0, str(PLUGIN))

from lark_stock.config import load_config  # noqa: E402
from lark_stock.service import LarkStock  # noqa: E402


def _mask(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "(empty)"
    if len(text) <= 6:
        return f"len={len(text)}"
    return f"{text[:4]}…{text[-2:]} len={len(text)}"


def main() -> int:
    config = load_config()
    print("domain=", config.domain)
    print("app_id=", _mask(config.app_id))
    print("app_secret=", _mask(config.app_secret))
    print("im_receive_id_type=", config.im_receive_id_type)
    print("im_receive_id=", _mask(config.im_receive_id))
    if not config.im_receive_id:
        print("error=LARK_IM_RECEIVE_ID is empty")
        return 1
    service = LarkStock(config)
    message_id = service.messenger.send_text("【测试】vibe-astock lark-stock 插件连通性检查")
    print("ok=true")
    print("message_id=", message_id)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ok=false error={type(exc).__name__}: {exc}")
        raise SystemExit(1)
