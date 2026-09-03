#!/usr/bin/env python3
"""探测财联社 level 字段分布。"""

from __future__ import annotations

import time
from collections import Counter

from vr.message import cls


def main() -> None:
    seen: set[int] = set()
    levels: Counter[str] = Counter()
    last_time = int(time.time())
    pages = 0
    max_pages = 20

    while pages < max_pages:
        page = cls._fetch_roll_page(last_time=last_time, rn=50)
        pages += 1
        if not page:
            break
        for item in page:
            mid = int(item.get("id") or 0)
            if mid <= 0 or mid in seen:
                continue
            seen.add(mid)
            lv = str(item.get("level") or "(空)").upper()
            levels[lv] += 1
        try:
            tail_ctime = int(page[-1].get("ctime") or 0)
        except (TypeError, ValueError):
            break
        if tail_ctime <= 0 or tail_ctime >= last_time:
            break
        last_time = tail_ctime - 1

    print(f"翻页 {pages} 页，共 {len(seen)} 条\n")
    print("=== level 分布 ===")
    for lv, cnt in levels.most_common():
        print(f"  {lv}: {cnt}")

    # 打印第一条的 keys 供参考
    page0 = cls._fetch_roll_page(last_time=int(time.time()), rn=1)
    if page0:
        print(f"\n=== 单条字段 keys ===")
        print(sorted(page0[0].keys()))


if __name__ == "__main__":
    main()
