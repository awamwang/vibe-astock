#!/usr/bin/env python3
"""打印财联社电报 API 字段。"""

from __future__ import annotations

import json
import time

from vr.message import cls


def main() -> None:
    items = cls._fetch_roll_page(last_time=int(time.time()), rn=5)
    if not items:
        print("无数据")
        return
    keys = sorted(items[0].keys())
    print(f"共 {len(items)} 条，字段数 {len(keys)}")
    print("keys:", keys)
    print()
    for i, item in enumerate(items[:3], 1):
        snap = {
            "id": item.get("id"),
            "level": item.get("level"),
            "bold": item.get("bold"),
            "recommend": item.get("recommend"),
            "jpush": item.get("jpush"),
            "is_top": item.get("is_top"),
            "title": (item.get("title") or item.get("content") or "")[:80],
        }
        print(f"--- {i} ---")
        print(json.dumps(snap, ensure_ascii=False))


if __name__ == "__main__":
    main()
