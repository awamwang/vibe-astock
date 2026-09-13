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


def canonicalize_name(raw: str) -> str:
    """名称归一：空白清理 + 题材别名表。"""
    t = norm_name(raw)
    if not t:
        return t
    try:
        from .theme_normalize import canonicalize_tag  # noqa: PLC0415

        return canonicalize_tag(t)
    except Exception:  # noqa: BLE001
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
        for key in (name_s, canonicalize_name(name_s)):
            if key and key not in self.by_name:
                self.by_name[key] = code_s

    def extend(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            self.add(str(row.get("code") or ""), str(row.get("name") or ""), **{
                k: v for k, v in row.items() if k not in ("code", "name")
            })

    def resolve_name(self, name: str) -> Optional[str]:
        """名称 → 开盘啦 code；未命中返回 None。"""
        mapped = canonicalize_name(name)
        if not mapped:
            return None
        return self.by_name.get(mapped) or self.by_name.get(norm_name(name))

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

    kpl_code = idx.resolve_name(mapped or name_s)
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
