"""板块方言映射 —— 在不同数据源的板块标识之间对齐。

方言：
  · ``ths`` —— 同花顺板块（kind + id + name，关注板块配置口径）
  · ``kpl`` —— 开盘啦概念/行业（PlateID 如 801660 + name）
  · ``raw`` —— 自由文本名称

对齐顺序（与 ``ths_block.processor`` 一致）：去空格归一 → 题材别名 canonicalize → 名称精确匹配。
不做模糊相似度；未命中返回 unmatched，由调用方决定是否入待匹配队列。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

LANG_THS = "ths"
LANG_KPL = "kpl"
LANG_RAW = "raw"


def norm_name(raw: str) -> str:
    """去空白，与 ths_block / theme_normalize 口径一致。"""
    return str(raw or "").replace(" ", "").replace("\u3000", "").strip()


# 地域名尾缀：匹配时忽略（长后缀优先）
_REGION_SUFFIXES = (
    "特别行政区",
    "壮族自治区",
    "回族自治区",
    "维吾尔自治区",
    "自治区",
    "省",
    "市",
)


def strip_region_suffix(name: str) -> str:
    """去掉地域名尾部的省/市/自治区等行政后缀。"""
    t = norm_name(name)
    if not t:
        return t
    for suf in _REGION_SUFFIXES:
        if len(t) > len(suf) and t.endswith(suf):
            return t[: -len(suf)]
    return t


def canonicalize_name(raw: str, *, region: bool = False) -> str:
    """名称归一：空白清理 + 题材别名表；地域可再去行政后缀。"""
    t = norm_name(raw)
    if not t:
        return t
    try:
        from .theme_normalize import canonicalize_tag  # noqa: PLC0415

        t = canonicalize_tag(t)
    except Exception:  # noqa: BLE001
        pass
    if region:
        return strip_region_suffix(t) or t
    return t


class KplNameIndex:
    """开盘啦 code ↔ name 索引（内存）。"""

    def __init__(self) -> None:
        self.by_code: dict[str, dict[str, Any]] = {}
        self.by_name: dict[str, str] = {}

    def add(self, code: str, name: str, **extra: Any) -> None:
        code_s = str(code or "").strip()
        name_s = norm_name(name)
        if not code_s or not name_s:
            return
        row = {"code": code_s, "name": str(name or "").strip() or name_s, **extra}
        self.by_code[code_s] = row
        keys = {name_s, canonicalize_name(name_s)}
        # 地域类型额外登记去后缀键，便于「广东」↔「广东省」
        if str(extra.get("kind") or "") == "region":
            keys.add(canonicalize_name(name_s, region=True))
            keys.add(strip_region_suffix(name_s))
        for key in keys:
            if key and key not in self.by_name:
                self.by_name[key] = code_s

    def extend(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            self.add(str(row.get("code") or ""), str(row.get("name") or ""), **{
                k: v for k, v in row.items() if k not in ("code", "name")
            })

    def resolve_name(self, name: str, *, region: bool = False) -> Optional[str]:
        """名称 → 开盘啦 code；未命中返回 None。"""
        mapped = canonicalize_name(name, region=region)
        if not mapped:
            return None
        hit = self.by_name.get(mapped) or self.by_name.get(norm_name(name))
        if hit:
            return hit
        if region:
            return None
        # 非地域调用时仍尝试去后缀，兼容目录混排
        stripped = canonicalize_name(name, region=True)
        if stripped and stripped != mapped:
            return self.by_name.get(stripped)
        return None

    def get(self, code: str) -> Optional[dict[str, Any]]:
        return self.by_code.get(str(code or "").strip())


def build_kpl_index(rows: Iterable[dict[str, Any]] | None = None) -> KplNameIndex:
    """从开盘啦榜单/点查行构建索引。"""
    idx = KplNameIndex()
    if rows:
        idx.extend(rows)
    return idx


def resolve_to_kpl(
    *,
    name: str = "",
    code: str = "",
    kind: str = "",
    index: KplNameIndex | None = None,
) -> dict[str, Any]:
    """把同花顺关注项或自由名称解析到开盘啦。

    返回::
      {
        "status": "matched" | "unmatched" | "empty",
        "lang": "kpl",
        "code": "...",
        "name": "...",
        "mapped": "归一后名称",
        "source_kind": kind,
        "source_id": 原始 ths id（若有）,
      }
    """
    code_s = str(code or "").strip()
    name_s = norm_name(name)
    mapped = canonicalize_name(name_s or code_s)
    if not code_s and not mapped:
        return {
            "status": "empty",
            "lang": LANG_KPL,
            "code": "",
            "name": "",
            "mapped": "",
            "source_kind": str(kind or "").strip(),
            "source_id": "",
        }

    idx = index or KplNameIndex()

    # 已是开盘啦 PlateID（通常 6 位数字 80xxxx）
    if code_s and code_s in idx.by_code:
        hit = idx.by_code[code_s]
        return {
            "status": "matched",
            "lang": LANG_KPL,
            "code": code_s,
            "name": str(hit.get("name") or name_s or code_s),
            "mapped": mapped or norm_name(hit.get("name") or ""),
            "source_kind": str(kind or "").strip(),
            "source_id": code_s,
        }
    if code_s and code_s.isdigit() and code_s.startswith("80") and len(code_s) == 6:
        # 无索引条目时仍可点查
        return {
            "status": "matched",
            "lang": LANG_KPL,
            "code": code_s,
            "name": name_s or code_s,
            "mapped": mapped or name_s,
            "source_kind": str(kind or "").strip(),
            "source_id": code_s,
        }

    is_region = str(kind or "").strip() == "region"
    if is_region:
        mapped = canonicalize_name(name_s or code_s, region=True) or mapped
    kpl_code = idx.resolve_name(mapped or name_s, region=is_region)
    if kpl_code:
        hit = idx.get(kpl_code) or {}
        return {
            "status": "matched",
            "lang": LANG_KPL,
            "code": kpl_code,
            "name": str(hit.get("name") or name_s or kpl_code),
            "mapped": mapped or name_s,
            "source_kind": str(kind or "").strip(),
            "source_id": code_s,
        }

    return {
        "status": "unmatched",
        "lang": LANG_KPL,
        "code": "",
        "name": name_s,
        "mapped": mapped,
        "source_kind": str(kind or "").strip(),
        "source_id": code_s,
    }


def resolve_ths_block(
    block: dict[str, Any],
    index: KplNameIndex | None = None,
) -> dict[str, Any]:
    """关注板块配置项 → 开盘啦解析结果。"""
    return resolve_to_kpl(
        name=str(block.get("name") or ""),
        code=str(block.get("id") or ""),
        kind=str(block.get("kind") or ""),
        index=index,
    )
