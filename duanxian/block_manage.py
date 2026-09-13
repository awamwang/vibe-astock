"""板块管理 —— 同花顺 + 开盘啦融合快照。

按名称（方言归一）合并；字段取并集，缺失留空。
开盘啦侧经 ``kpl_blocks.ensure`` 初始化，自动日更最多一次。
"""

from __future__ import annotations

from typing import Any

from . import block_dialect as dialect
from . import kpl_blocks

# 同花顺 kind → 开盘啦结构 kind
_KIND_PAIR = {
    "conception": "concept",
    "industry": "industry",
    "region": "region",
}


def _ths_snapshot() -> dict[str, Any]:
    try:
        from ths_block.service import get_snapshot  # noqa: PLC0415

        return get_snapshot()
    except Exception:  # noqa: BLE001
        return {
            "updated_at": None,
            "ths_dir": None,
            "kinds": {},
            "errors": [],
            "empty": True,
        }


def _blank_unified(*, name: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "sources": [],
        "has_ths": False,
        "has_kpl": False,
        # 同花顺
        "kind": "",
        "kind_label": "",
        "id": "",
        "code": "",
        "node_type": "flat",
        "tree_path": name,
        "depth": None,
        "parent_id": None,
        "tree_order": None,
        "custom_type": None,
        "dynamic_kind": None,
        "query_key": None,
        "hex_id": None,
        "stock_count": None,
        # 开盘啦
        "kpl_code": "",
        "kpl_kind": "",
        "kpl_kind_label": "",
        "kpl_power": None,
        "kpl_pct": None,
        "kpl_speed": None,
        "kpl_m_net": None,
        "kpl_sort": None,
    }


def _apply_ths(row: dict[str, Any], ths: dict[str, Any]) -> None:
    row["has_ths"] = True
    if "ths" not in row["sources"]:
        row["sources"].append("ths")
    for key in (
        "kind", "kind_label", "id", "code", "node_type", "tree_path",
        "depth", "parent_id", "tree_order", "custom_type", "dynamic_kind",
        "query_key", "hex_id", "stock_count",
    ):
        if key in ths and ths[key] is not None:
            row[key] = ths[key]
    if not row.get("name"):
        row["name"] = str(ths.get("name") or ths.get("id") or "")


def _apply_kpl(row: dict[str, Any], kpl: dict[str, Any]) -> None:
    row["has_kpl"] = True
    if "kpl" not in row["sources"]:
        row["sources"].append("kpl")
    row["kpl_code"] = str(kpl.get("code") or row.get("kpl_code") or "")
    row["kpl_kind"] = str(kpl.get("kind") or row.get("kpl_kind") or "")
    row["kpl_kind_label"] = str(kpl.get("kind_label") or row.get("kpl_kind_label") or "")
    for src, dst in (
        ("power", "kpl_power"),
        ("pct", "kpl_pct"),
        ("speed", "kpl_speed"),
        ("m_net", "kpl_m_net"),
        ("sort", "kpl_sort"),
    ):
        if row.get(dst) is None and kpl.get(src) is not None:
            row[dst] = kpl[src]
    if not row.get("name"):
        row["name"] = str(kpl.get("name") or kpl.get("code") or "")
    if not row.get("tree_path"):
        row["tree_path"] = row["name"]
    if not row.get("kind") and row.get("kpl_kind"):
        # 仅开盘啦时用映射后的同花顺 kind 便于筛选
        rev = {v: k for k, v in _KIND_PAIR.items()}
        mapped = rev.get(row["kpl_kind"])
        if mapped:
            row["kind"] = mapped
            row["kind_label"] = {
                "conception": "概念",
                "industry": "行业",
                "region": "地域",
            }.get(mapped, row["kpl_kind_label"])
        elif row["kpl_kind"] == "hot":
            row["kind"] = "conception"
            row["kind_label"] = "概念"


def _kpl_by_name(kpl_snap: dict[str, Any]) -> dict[str, list[dict]]:
    """归一名称 → 开盘啦行列表（同名可能跨 kind）。"""
    buckets: dict[str, list[dict]] = {}
    for row in kpl_blocks.all_rows(kpl_snap):
        key = dialect.canonicalize_name(str(row.get("name") or ""))
        if not key:
            continue
        buckets.setdefault(key, []).append(row)
    return buckets


def _pick_kpl_for_ths_kind(candidates: list[dict], ths_kind: str) -> dict | None:
    """为同花顺行挑选开盘啦行：结构 kind 优先，否则人气。"""
    if not candidates:
        return None
    want = _KIND_PAIR.get(ths_kind)
    if want:
        for c in candidates:
            if c.get("kind") == want:
                return c
    for c in candidates:
        if c.get("kind") == "hot":
            return c
    return candidates[0]


def _merge_kind(
    *,
    ths_kind: str,
    ths_rows: list[dict],
    kpl_buckets: dict[str, list[dict]],
    used_kpl: set[str],
) -> list[dict]:
    out: list[dict] = []
    for ths in ths_rows:
        if not isinstance(ths, dict):
            continue
        name = str(ths.get("name") or ths.get("id") or "")
        row = _blank_unified(name=name)
        _apply_ths(row, ths)
        key = dialect.canonicalize_name(name)
        node_type = str(ths.get("node_type") or "")
        if key and node_type != "branch":
            hit = _pick_kpl_for_ths_kind(kpl_buckets.get(key) or [], ths_kind)
            if hit:
                _apply_kpl(row, hit)
                used_kpl.add(str(hit.get("code") or ""))
                # 同名另有人气 PlateID 时补上（结构代码已写入则保留结构，另存人气优先覆盖点查码）
                for alt in kpl_buckets.get(key) or []:
                    if alt.get("kind") == "hot" and str(alt.get("code") or "") != row["kpl_code"]:
                        # 点查口径优先人气 PlateID
                        row["kpl_code"] = str(alt.get("code") or row["kpl_code"])
                        if alt.get("power") is not None:
                            row["kpl_power"] = alt.get("power")
                        used_kpl.add(str(alt.get("code") or ""))
                        break
        out.append(row)

    # 开盘啦独有：结构 kind 对齐；人气未匹配的归入概念
    kpl_kind = _KIND_PAIR.get(ths_kind)
    extra_kinds = {kpl_kind} if kpl_kind else set()
    if ths_kind == "conception":
        extra_kinds.add("hot")
    for key, cands in kpl_buckets.items():
        for cand in cands:
            if cand.get("kind") not in extra_kinds:
                continue
            code = str(cand.get("code") or "")
            if not code or code in used_kpl:
                continue
            row = _blank_unified(name=str(cand.get("name") or code))
            _apply_kpl(row, cand)
            # 保证 kind 字段与当前页签一致
            row["kind"] = ths_kind
            row["kind_label"] = {
                "conception": "概念",
                "industry": "行业",
                "region": "地域",
            }.get(ths_kind, ths_kind)
            used_kpl.add(code)
            out.append(row)
    return out


def _merge_ths_only(ths_rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for ths in ths_rows:
        if not isinstance(ths, dict):
            continue
        row = _blank_unified(name=str(ths.get("name") or ths.get("id") or ""))
        _apply_ths(row, ths)
        out.append(row)
    return out


def build_merged(*, ths_snap: dict[str, Any], kpl_snap: dict[str, Any]) -> dict[str, list[dict]]:
    """按同花顺 kind 产出融合行。"""
    kpl_buckets = _kpl_by_name(kpl_snap)
    used_kpl: set[str] = set()
    merged: dict[str, list[dict]] = {}
    ths_kinds = ths_snap.get("kinds") or {}

    for ths_kind in ("conception", "industry", "region", "custom", "daily"):
        entry = ths_kinds.get(ths_kind) or {}
        ths_rows = list(entry.get("rows") or []) if isinstance(entry, dict) else []
        if ths_kind in _KIND_PAIR:
            merged[ths_kind] = _merge_kind(
                ths_kind=ths_kind,
                ths_rows=ths_rows,
                kpl_buckets=kpl_buckets,
                used_kpl=used_kpl,
            )
        else:
            merged[ths_kind] = _merge_ths_only(ths_rows)

    # 同花顺尚未加载时，仍返回开盘啦侧
    if not any(merged.get(k) for k in _KIND_PAIR):
        for ths_kind, kpl_kind in _KIND_PAIR.items():
            if merged.get(ths_kind):
                continue
            rows: list[dict] = []
            for cand in kpl_blocks.all_rows(kpl_snap):
                if cand.get("kind") == kpl_kind or (ths_kind == "conception" and cand.get("kind") == "hot"):
                    code = str(cand.get("code") or "")
                    if code in used_kpl:
                        continue
                    row = _blank_unified(name=str(cand.get("name") or code))
                    _apply_kpl(row, cand)
                    row["kind"] = ths_kind
                    row["kind_label"] = {
                        "conception": "概念",
                        "industry": "行业",
                        "region": "地域",
                    }.get(ths_kind, ths_kind)
                    used_kpl.add(code)
                    rows.append(row)
            merged[ths_kind] = rows

    return merged


def snapshot(*, ensure_kpl: bool = True, force_kpl: bool = False) -> dict[str, Any]:
    """板块管理快照：同花顺缓存 + 开盘啦目录（可自动日更）+ 融合行。"""
    if ensure_kpl:
        kpl_snap = kpl_blocks.ensure(force=force_kpl)
    else:
        kpl_snap = kpl_blocks.get_snapshot()
    ths_snap = _ths_snapshot()
    merged = build_merged(ths_snap=ths_snap, kpl_snap=kpl_snap)
    return {
        "updated_at": ths_snap.get("updated_at") or kpl_snap.get("updated_at"),
        "ths": ths_snap,
        "kpl": {
            "updated_at": kpl_snap.get("updated_at"),
            "fetched_date": kpl_snap.get("fetched_date"),
            "from_cache": bool(kpl_snap.get("from_cache")),
            "available": bool(kpl_snap.get("available")),
            "errors": list(kpl_snap.get("errors") or []),
            "kinds": {
                k: {
                    "kind": v.get("kind"),
                    "kind_label": v.get("kind_label"),
                    "count": v.get("count"),
                    "api_count": v.get("api_count"),
                }
                for k, v in (kpl_snap.get("kinds") or {}).items()
                if isinstance(v, dict)
            },
        },
        "merged": merged,
        "linker_unavailable": bool(ths_snap.get("linker_unavailable")),
        "linker_message": ths_snap.get("linker_message"),
        "ths_dir": ths_snap.get("ths_dir"),
        "errors": list(ths_snap.get("errors") or []) + list(kpl_snap.get("errors") or []),
    }


def refresh(*, ths_dir: str | None = None, refresh_ths: bool = True) -> dict[str, Any]:
    """手动刷新：同花顺全量（可选）+ 开盘啦强制重拉。"""
    if refresh_ths:
        try:
            from ths_block.service import refresh_cache  # noqa: PLC0415

            refresh_cache(ths_dir=ths_dir)
        except Exception:  # noqa: BLE001
            pass
    return snapshot(ensure_kpl=True, force_kpl=True)
