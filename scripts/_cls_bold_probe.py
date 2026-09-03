#!/usr/bin/env python3
"""检查财联社 bold / level 等标红相关字段。"""

from __future__ import annotations

import json
import time

from vr.message import cls


def main() -> None:
    items = cls._fetch_roll_page(last_time=int(time.time()), rn=50)
    bold_vals: set = set()
    level_vals: set = set()
    bold_items = []

    for item in items:
        bold_vals.add(repr(item.get("bold")))
        level_vals.add(repr(item.get("level")))
        if item.get("bold"):
            bold_items.append(item)

    print("=== 最新 50 条 bold 取值 ===")
    print(bold_vals)
    print("\n=== 最新 50 条 level 取值 ===")
    print(level_vals)
    print(f"\n=== bold=True 条数: {len(bold_items)} ===")

    # 翻页找 level=A 或 bold=1
    seen: set[int] = set()
    a_items = []
    bold_examples = []
    last_time = int(time.time())
    for _ in range(30):
        page = cls._fetch_roll_page(last_time=last_time, rn=50)
        if not page:
            break
        for item in page:
            mid = int(item.get("id") or 0)
            if mid <= 0 or mid in seen:
                continue
            seen.add(mid)
            if str(item.get("level") or "").upper() == "A":
                a_items.append(item)
            if item.get("bold") and len(bold_examples) < 3:
                bold_examples.append(item)
        if len(a_items) >= 3 and len(bold_examples) >= 3:
            break
        try:
            tail_ctime = int(page[-1].get("ctime") or 0)
        except (TypeError, ValueError):
            break
        if tail_ctime <= 0 or tail_ctime >= last_time:
            break
        last_time = tail_ctime - 1

    print(f"\n翻页 {len(seen)} 条: level=A 共 {len(a_items)} 条, bold 示例 {len(bold_examples)} 条")

    if a_items:
        print("\n=== level=A 示例 ===")
        for i, item in enumerate(a_items[:3], 1):
            print(json.dumps({k: item.get(k) for k in ("id", "ctime", "level", "bold", "title", "content")}, ensure_ascii=False)[:500])
            print()

    if bold_examples:
        print("\n=== bold 示例 ===")
        for i, item in enumerate(bold_examples[:3], 1):
            print(f"--- {i} ---")
            print(f"id={item.get('id')} level={item.get('level')} bold={item.get('bold')}")
            body = (item.get("title") or item.get("content") or "")[:200]
            print(body)
            print()


if __name__ == "__main__":
    main()
