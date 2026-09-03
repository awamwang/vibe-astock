#!/usr/bin/env python3
"""打印找到的 level=A 条目详情。"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request

_CLS_SV = "8.7.9"
_CLS_APP = "CailianpressWeb"
_CLS_ROLL_URL = "https://www.cls.cn/v1/roll/get_roll_list"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


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
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": "https://www.cls.cn/telegraph",
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return (body.get("data") or {}).get("roll_data") or []


def find_a(category: str, limit: int = 5) -> list[dict]:
    found: list[dict] = []
    seen: set[int] = set()
    last = int(time.time())
    while len(found) < limit:
        page = fetch_roll(category=category, rn=50, last_time=last)
        if not page:
            break
        for item in page:
            mid = int(item.get("id") or 0)
            if mid <= 0 or mid in seen:
                continue
            seen.add(mid)
            if str(item.get("level") or "").upper() == "A":
                found.append(item)
                if len(found) >= limit:
                    break
        try:
            tail = int(page[-1].get("ctime") or 0)
        except (TypeError, ValueError):
            break
        if tail <= 0 or tail >= last:
            break
        last = tail - 1
    return found


def ts(ct: int | float | None) -> str:
    from datetime import datetime, timezone, timedelta
    bj = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(int(ct), bj).strftime("%Y-%m-%d %H:%M:%S")


def show(items: list[dict]) -> None:
    for i, item in enumerate(items, 1):
        title = (item.get("title") or item.get("content") or "")[:150]
        print(f"--- A级 #{i} ---")
        print(f"id={item.get('id')} time={ts(item.get('ctime'))}")
        print(f"level={item.get('level')} bold={item.get('bold')} recommend={item.get('recommend')} jpush={item.get('jpush')}")
        print(title)
        print()


def main() -> None:
    print("=== 全部 feed 中的 level=A（最多5条）===")
    show(find_a("", 5))
    print("=== red 分类中的 level=A（最多5条）===")
    show(find_a("red", 5))


if __name__ == "__main__":
    main()
