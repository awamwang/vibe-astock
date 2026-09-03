#!/usr/bin/env python3
"""拉取财联社最新 N 条电报，统计 level 并打印 A 级示例。"""

from __future__ import annotations

import argparse
import time
from collections import Counter

from vr.message import cls


def _body(item: dict) -> str:
    title = (item.get("title") or "").strip()
    content = (item.get("content") or "").strip()
    if title and content and title not in content:
        return f"{title}\n{content}"
    return title or content


def _print_example(idx: int, item: dict) -> None:
    print(f"--- 示例 {idx} ---")
    print(f"id: {item.get('id')}")
    print(f"时间: {cls._ts_to_str(item.get('ctime'))}")
    print(f"level: {item.get('level')}")
    print(f"题材: {cls.extract_subjects(item)}")
    print(f"内容: {_body(item)[:400]}")
    print()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("-n", type=int, default=50, help="拉取条数")
    p.add_argument("--pages", type=int, default=5, help="翻页找 A 级时最多页数")
    args = p.parse_args()

    items = cls._fetch_roll_page(last_time=int(time.time()), rn=args.n)
    print(f"共拉取 {len(items)} 条\n")

    levels = Counter(str(i.get("level") or "(空)").upper() for i in items)
    print("=== 级别统计 ===")
    for lv in sorted(levels.keys()):
        print(f"  {lv}: {levels[lv]}")

    a_in_batch = [i for i in items if str(i.get("level") or "").upper() == "A"]
    a_examples = list(a_in_batch[:3])

    if len(a_examples) < 3:
        seen = {int(i.get("id") or 0) for i in items}
        last_time = int(time.time())
        for _ in range(args.pages):
            if len(a_examples) >= 3:
                break
            page = cls._fetch_roll_page(last_time=last_time, rn=args.n)
            if not page:
                break
            for item in page:
                mid = int(item.get("id") or 0)
                if mid <= 0 or mid in seen:
                    continue
                seen.add(mid)
                if str(item.get("level") or "").upper() == "A":
                    a_examples.append(item)
                    if len(a_examples) >= 3:
                        break
            try:
                tail_ctime = int(page[-1].get("ctime") or 0)
            except (TypeError, ValueError):
                break
            if tail_ctime <= 0 or tail_ctime >= last_time:
                break
            last_time = tail_ctime - 1

    print(f"\n=== A 级示例（本批 {len(a_in_batch)} 条 A，展示 {min(3, len(a_examples))} 条）===\n")
    if a_examples:
        for idx, item in enumerate(a_examples[:3], 1):
            _print_example(idx, item)
    else:
        print("（本批及翻页范围内未找到 A 级电报）")


if __name__ == "__main__":
    main()
