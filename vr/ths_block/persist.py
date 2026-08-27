"""同花顺自定义板块动态项落盘（供 ths-linker 离线读取）。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any

_BEIJING = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(_BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _target_path() -> str:
    env = os.environ.get("THS_CUSTOM_BLOCKS_JSON", "").strip()
    if env:
        return env
    return os.path.expanduser("~/.vibe-astock/同花顺自定义板块.json")


def extract_dynamic_blocks(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """从 custom 板块快照中提取 dynamic 类型项。"""
    meta_map = entry.get("blocks_meta") or {}
    out: dict[str, dict[str, Any]] = {}
    for bid, meta in meta_map.items():
        if not isinstance(meta, dict):
            continue
        if str(meta.get("custom_type") or "") != "dynamic":
            continue
        out[str(bid)] = dict(meta)
    return out


def save_dynamic_custom_blocks(*, ths_dir: str, entry: dict[str, Any]) -> dict[str, Any]:
    """将 dynamic 自定义板块写入 JSON 落盘文件。"""
    blocks = extract_dynamic_blocks(entry)
    path = _target_path()
    payload = {
        "updated_at": _now(),
        "ths_dir": ths_dir,
        "count": len(blocks),
        "blocks": blocks,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return payload
