#!/usr/bin/env python3
"""对比财联社 level / bold / category=red 与标红的关系。"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from collections import Counter

_CLS_SV = "8.7.9"
_CLS_APP = "CailianpressWeb"
_CLS_ROLL_URL = "https://www.cls.cn/v1/roll/get_roll_list"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": UA,
        "Referer": "https://www.cls.cn/telegraph",
        "Accept": "application/json, text/plain, */*",
    }


def _sign(params: dict[str, str]) -> str:
    ordered = sorted((k, v) for k, v in params.items() if v is not None)
    qs = urllib.parse.urlencode(ordered)
    sha1 = hashlib.sha1(qs.encode("utf-8")).hexdigest()
    return hashlib.md5(sha1.encode("utf-8")).hexdigest()


def fetch_roll(*, category: str = "", rn: int = 50, last_time: int | None = None) -> list[dict]:
    base: dict[str, str] = {
        "app": _CLS_APP,
        "category": category,
        "os": "web",
        "refresh_type": "1",
        "sv": _CLS_SV,
        "last_time": str(last_time or int(time.time())),
        "rn": str(rn),
    }
    base["sign"] = _sign({k: v for k, v in base.items() if k != "sign"})
    url = f"{_CLS_ROLL_URL}?{urllib.parse.urlencode(base)}"
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=25) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return (body.get("data") or {}).get("roll_data") or []


def stats(items: list[dict], label: str) -> None:
    levels = Counter(str(i.get("level") or "(空)").upper() for i in items)
    bolds = Counter(str(i.get("bold")) for i in items)
    print(f"\n=== {label} ({len(items)} 条) ===")
    print(f"  level: {dict(levels)}")
    print(f"  bold:  {dict(bolds)}")
    bold1 = [i for i in items if str(i.get("bold")) in ("1", "True", "true")]
    print(f"  bold=1 条数: {len(bold1)}")
    if bold1:
        print("  bold=1 示例 level:", [str(i.get("level")) for i in bold1[:5]])


def main() -> None:
    all_items = fetch_roll(category="", rn=50)
    red_items = fetch_roll(category="red", rn=50)

    stats(all_items, "全部（category=空）")
    stats(red_items, "加红（category=red）")

    # 交叉：全部里 bold=1 是否在 red 分类也出现
    all_bold_ids = {int(i.get("id") or 0) for i in all_items if str(i.get("bold")) in ("1", "True")}
    red_ids = {int(i.get("id") or 0) for i in red_items}
    overlap = all_bold_ids & red_ids
    print(f"\n=== 交叉验证 ===")
    print(f"  全部前50中 bold=1 的 id 数: {len(all_bold_ids)}")
    print(f"  red 分类前50 id 数: {len(red_ids)}")
    print(f"  重叠 id 数: {len(overlap)}")

    print("\n=== red 分类前 3 条示例 ===")
    for idx, item in enumerate(red_items[:3], 1):
        title = (item.get("title") or item.get("content") or "")[:120]
        print(f"--- {idx} ---")
        print(f"id={item.get('id')} level={item.get('level')} bold={item.get('bold')}")
        print(title)
        print()

    # 翻页 red 分类看 level 分布
    seen: set[int] = set()
    red_levels: Counter[str] = Counter()
    last = int(time.time())
    for _ in range(5):
        page = fetch_roll(category="red", rn=50, last_time=last)
        if not page:
            break
        for item in page:
            mid = int(item.get("id") or 0)
            if mid <= 0 or mid in seen:
                continue
            seen.add(mid)
            red_levels[str(item.get("level") or "(空)").upper()] += 1
        try:
            tail = int(page[-1].get("ctime") or 0)
        except (TypeError, ValueError):
            break
        if tail <= 0 or tail >= last:
            break
        last = tail - 1

    print(f"=== red 分类翻页 {len(seen)} 条 level 分布 ===")
    for lv, cnt in red_levels.most_common():
        print(f"  {lv}: {cnt}")


if __name__ == "__main__":
    main()
