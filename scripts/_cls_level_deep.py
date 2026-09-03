#!/usr/bin/env python3
"""深挖财联社 level=A 是否还存在，以及 bold/recommend 等字段。"""

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


def fetch_roll(*, category: str = "", rn: int = 50, last_time: int) -> list[dict]:
    base: dict[str, str] = {
        "app": _CLS_APP,
        "category": category,
        "os": "web",
        "refresh_type": "1",
        "sv": _CLS_SV,
        "last_time": str(last_time),
        "rn": str(rn),
    }
    base["sign"] = _sign({k: v for k, v in base.items() if k != "sign"})
    url = f"{_CLS_ROLL_URL}?{urllib.parse.urlencode(base)}"
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=25) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return (body.get("data") or {}).get("roll_data") or []


def scan(category: str, max_items: int = 3000) -> tuple[Counter, list[dict], list[dict]]:
    seen: set[int] = set()
    levels: Counter[str] = Counter()
    bold_vals: Counter[str] = Counter()
    a_items: list[dict] = []
    bold1_items: list[dict] = []
    last = int(time.time())

    while len(seen) < max_items:
        page = fetch_roll(category=category, rn=50, last_time=last)
        if not page:
            break
        for item in page:
            mid = int(item.get("id") or 0)
            if mid <= 0 or mid in seen:
                continue
            seen.add(mid)
            lv = str(item.get("level") or "(空)").upper()
            levels[lv] += 1
            bold_vals[str(item.get("bold"))] += 1
            if lv == "A":
                a_items.append(item)
            if str(item.get("bold")) == "1" and len(bold1_items) < 5:
                bold1_items.append(item)
        try:
            tail = int(page[-1].get("ctime") or 0)
        except (TypeError, ValueError):
            break
        if tail <= 0 or tail >= last:
            break
        last = tail - 1

    return levels, a_items, bold1_items


def sample_fields(item: dict) -> dict:
    keys = (
        "id", "ctime", "level", "bold", "recommend", "is_top", "type",
        "jpush", "category", "status", "title", "content",
    )
    return {k: item.get(k) for k in keys if k in item}


def main() -> None:
    print("=== 全部 feed 翻页 3000 条 ===")
    all_levels, all_a, all_bold = scan("", 3000)
    print("level:", dict(all_levels))
    print(f"level=A 条数: {sum(all_levels[k] for k in all_levels if k == 'A')}")

    print("\n=== red 分类 feed 翻页 1000 条 ===")
    red_levels, red_a, red_bold = scan("red", 1000)
    print("level:", dict(red_levels))
    print(f"level=A 条数: {sum(red_levels[k] for k in red_levels if k == 'A')}")

    if all_bold:
        print("\n=== 全部 feed 中 bold=1 示例 ===")
        for item in all_bold[:3]:
            print(json.dumps(sample_fields(item), ensure_ascii=False)[:600])

    if red_bold:
        print("\n=== red 分类 bold=1 示例 ===")
        for item in red_bold[:3]:
            print(json.dumps(sample_fields(item), ensure_ascii=False)[:600])

    # 对比 red 分类首条与全部中同 id
    red_page = fetch_roll(category="red", rn=5, last_time=int(time.time()))
    if red_page:
        rid = int(red_page[0].get("id") or 0)
        print(f"\n=== red 首条 id={rid} 字段快照 ===")
        print(json.dumps(sample_fields(red_page[0]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
