#!/usr/bin/env python3
"""财联社两路数据源对比：AkShare vs cls.cn 直连。

用法：
  python scripts/test_cls_sources.py
  python scripts/test_cls_sources.py --limit 10
  CLS_SIGN=xxx python scripts/test_cls_sources.py --sign-only   # 仅测直连（手动 sign）

sign 可本地算法生成（对照 RSSHub lib/routes/cls/utils.ts），也可从浏览器抓包复制。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any
from urllib.parse import urlencode

import requests

# RSSHub cls/utils.ts 当前版本号，改版时对照更新
_CLS_SV = "8.7.9"
_CLS_APP = "CailianpressWeb"
_CLS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.cls.cn/telegraph",
    "Accept": "application/json, text/plain, */*",
}


def 生成_cls_sign(参数字典: dict[str, str]) -> str:
    """sign = MD5(SHA1(按 key 排序后的 query string))，不含 sign 本身。"""
    有序 = sorted((k, v) for k, v in 参数字典.items() if v is not None)
    待签 = urlencode(有序)
    sha1 = hashlib.sha1(待签.encode("utf-8")).hexdigest()
    return hashlib.md5(sha1.encode("utf-8")).hexdigest()


def 构建_cls_查询(**extra: str) -> dict[str, str]:
    """构建带 sign 的查询参数（appName 键名与 RSSHub 一致）。"""
    base: dict[str, str] = {
        "appName": _CLS_APP,
        "os": "web",
        "sv": _CLS_SV,
    }
    base.update({k: v for k, v in extra.items() if v is not None})
    base["sign"] = 生成_cls_sign({k: v for k, v in base.items() if k != "sign"})
    return base


def 拉取_akshare_cls(limit: int = 10) -> list[dict[str, Any]]:
    """AkShare stock_info_global_cls → 扁平 dict 列表。"""
    import akshare as ak

    df = ak.stock_info_global_cls(symbol="全部")
    rows: list[dict[str, Any]] = []
    for _, r in df.head(limit).iterrows():
        rows.append(
            {
                "source": "akshare_cls",
                "title": str(r.get("标题", "") or ""),
                "content": str(r.get("内容", "") or ""),
                "date": str(r.get("发布日期", "") or ""),
                "time": str(r.get("发布时间", "") or ""),
            }
        )
    return rows


def 拉取_cls_电报直连(limit: int = 10, manual_sign: str | None = None) -> list[dict[str, Any]]:
    """cls.cn /api/cache?name=telegraph（RSSHub 维护路径）。"""
    if manual_sign:
        query = {
            "appName": _CLS_APP,
            "os": "web",
            "sv": _CLS_SV,
            "name": "telegraph",
            "sign": manual_sign,
        }
    else:
        query = 构建_cls_查询(name="telegraph")

    url = "https://www.cls.cn/api/cache"
    resp = requests.get(url, params=query, headers=_CLS_HEADERS, timeout=20)
    resp.raise_for_status()
    body = resp.json()

    roll = (body.get("data") or {}).get("roll_data") or []
    rows: list[dict[str, Any]] = []
    for item in roll[:limit]:
        rows.append(
            {
                "source": "cls_telegraph",
                "id": item.get("id"),
                "title": item.get("title") or item.get("content") or "",
                "content": item.get("content") or "",
                "ctime": item.get("ctime"),
                "url": item.get("shareurl"),
                "level": item.get("level"),  # 加红等级
                "subjects": [
                    s.get("subject_name") for s in (item.get("subjects") or [])
                ],
            }
        )
    return rows


def _打印区块(标题: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {标题}  ({len(rows)} 条)")
    print("=" * 60)
    for i, row in enumerate(rows, 1):
        print(f"\n--- [{i}] ---")
        print(json.dumps(row, ensure_ascii=False, indent=2))


def _打印_sign_说明() -> None:
    示例 = 构建_cls_查询(name="telegraph")
    print(
        """
【sign 获取方式】

方式 A — 本地算法（推荐，零手工）
  规则（对照 RSSHub lib/routes/cls/utils.ts）：
    1. 参与签名的参数：appName、os、sv，以及业务参数（如 name=telegraph）
    2. 按 key 字母序排序，拼成 query string（如 appName=CailianpressWeb&name=telegraph&os=web&sv=8.7.9）
    3. sign = MD5( SHA1(上述字符串).hexdigest() )

  本脚本已内置 `生成_cls_sign()` / `构建_cls_查询()`，正常运行即可。

方式 B — 浏览器抓包（接口改版时对照）
  1. 打开 https://www.cls.cn/telegraph
  2. F12 → Network → 筛选 Fetch/XHR
  3. 刷新页面，找请求：
       GET https://www.cls.cn/api/cache?name=telegraph&appName=...&sign=...
     或 GET https://www.cls.cn/v1/roll/get_roll_list?...
  4. 复制 Query String 里的 sign= 后面的 32 位 hex
  5. 临时使用：set CLS_SIGN=复制的sign  再运行本脚本 --sign-only

  注意：抓到的 sign 与当次请求的参数绑定，参数变了需重新抓或改用方式 A。

当前算法生成的示例请求参数：
"""
    )
    print(json.dumps(示例, ensure_ascii=False, indent=2))
    print(f"\n完整 URL 示例：")
    print(f"  https://www.cls.cn/api/cache?{urlencode(示例)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="财联社 AkShare vs cls.cn 电报对比")
    parser.add_argument("--limit", type=int, default=10, help="各源拉取条数")
    parser.add_argument("--akshare-only", action="store_true", help="仅测 AkShare")
    parser.add_argument("--cls-only", action="store_true", help="仅测 cls.cn 直连")
    parser.add_argument("--sign-only", action="store_true", help="仅测 cls.cn（可配合 CLS_SIGN）")
    parser.add_argument("--explain-sign", action="store_true", help="打印 sign 获取说明后退出")
    args = parser.parse_args()

    if args.explain_sign:
        _打印_sign_说明()
        return 0

    manual_sign = os.environ.get("CLS_SIGN") or None
    if manual_sign:
        print(f"[info] 使用环境变量 CLS_SIGN={manual_sign[:8]}...")

    ok = True

    if not args.cls_only and not args.sign_only:
        try:
            ak_rows = 拉取_akshare_cls(args.limit)
            _打印区块("AkShare · stock_info_global_cls", ak_rows)
        except Exception as e:
            ok = False
            print(f"\n[AkShare 失败] {e}", file=sys.stderr)

    if not args.akshare_only:
        try:
            cls_rows = 拉取_cls_电报直连(args.limit, manual_sign=manual_sign)
            _打印区块("cls.cn · /api/cache?name=telegraph", cls_rows)
        except Exception as e:
            ok = False
            print(f"\n[cls.cn 直连失败] {e}", file=sys.stderr)
            print("\n若 sign 算法已改版，运行：python scripts/test_cls_sources.py --explain-sign")
            _打印_sign_说明()

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
