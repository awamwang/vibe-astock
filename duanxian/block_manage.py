"""板块管理 —— 同花顺 / 开盘啦分列目录。

类型严格按各源原始分类，不做跨源并入页签。
同名时仅补全对方字段（字段并集），不改变所属类型。
开盘啦侧经 ``kpl_blocks.ensure`` 初始化，自动日更最多一次。
"""

from __future__ import annotations

from typing import Any

from . import block_dialect as dialect
from . import kpl_blocks

# 页签 key：ths:* / kpl:*
THS_KIND_KEYS = (
    ("ths:conception", "conception", "概念"),
    ("ths:industry", "industry", "行业"),
    ("ths:region", "region", "地域"),
    ("ths:custom", "custom", "自定义"),
    ("ths:daily", "daily", "每日动态"),
)
KPL_KIND_KEYS = (
    ("kpl:concept", "concept", "概念"),
    ("kpl:industry", "industry", "行业"),
    ("kpl:region", "region", "地域"),
    ("kpl:hot", "hot", "人气"),
)

# 同花顺 kind → 开盘啦同名结构 kind（仅用于字段补全，不并入页签）
_THS_TO_KPL_ENRICH = {
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
        "origin": "",  # ths | kpl —— 行所属原始来源类型体系
        "sources": [],
        "has_ths": False,
        "has_kpl": False,
        "kind": "",
        "kind_label": "",
        "ths_kind": "",
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
        "kpl_code": "",
        "kpl_kind": "",
        "kpl_kind_label": "",
        "kpl_power": None,
        "kpl_pct": None,
        "kpl_speed": None,
        "kpl_m_net": None,
        "kpl_sort": None,
    }


def _apply_ths(row: dict[str, Any], ths: dict[str, Any], *, native: bool = False) -> None:
    """写入同花顺字段。native=True 表示该行归属同花顺类型页签。"""
    row["has_ths"] = True
    if "ths" not in row["sources"]:
        row["sources"].append("ths")
    ths_kind = str(ths.get("kind") or "").strip()
    if ths_kind:
        row["ths_kind"] = ths_kind
    if native:
        for key in (
            "kind", "kind_label", "id", "code", "node_type", "tree_path",
            "depth", "parent_id", "tree_order", "custom_type", "dynamic_kind",
            "query_key", "hex_id", "stock_count",
        ):
            if key in ths and ths[key] is not None:
                row[key] = ths[key]
        if ths_kind:
            row["kind"] = ths_kind
    else:
        # 开盘啦行补全：只填空字段，不改 kind / origin
        for key in (
            "id", "code", "custom_type", "dynamic_kind",
            "query_key", "hex_id", "stock_count",
        ):
            if key in ths and ths[key] is not None and row.get(key) in (None, ""):
                row[key] = ths[key]
    if not row.get("name"):
        row["name"] = str(ths.get("name") or ths.get("id") or "")


def _apply_kpl(row: dict[str, Any], kpl: dict[str, Any], *, native: bool = False) -> None:
    """写入开盘啦字段。native=True 表示该行归属开盘啦类型页签。"""
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
    if native:
        row["kind"] = row["kpl_kind"]
        row["kind_label"] = row["kpl_kind_label"] or row["kind"]
        row["node_type"] = "flat"
        if not row.get("tree_path"):
            row["tree_path"] = row["name"]


def _kpl_by_name_for_kind(kpl_snap: dict[str, Any], kpl_kind: str) -> dict[str, dict]:
    """仅某一开盘啦原始类型的 名称→行。"""
    out: dict[str, dict] = {}
    entry = (kpl_snap.get("kinds") or {}).get(kpl_kind) or {}
    for row in entry.get("rows") or []:
        if not isinstance(row, dict):
            continue
        key = dialect.canonicalize_name(str(row.get("name") or ""))
        if key and key not in out:
            out[key] = row
    return out


def _ths_leaf_by_name(ths_snap: dict[str, Any], ths_kind: str | None = None) -> dict[str, dict]:
    """同花顺叶子 名称→行；可限定类型。"""
    out: dict[str, dict] = {}
    kinds = (ths_kind,) if ths_kind else ("conception", "industry", "region", "custom", "daily")
    for kind in kinds:
        entry = (ths_snap.get("kinds") or {}).get(kind) or {}
        for ths in entry.get("rows") or []:
            if not isinstance(ths, dict):
                continue
            if str(ths.get("node_type") or "") == "branch":
                continue
            key = dialect.canonicalize_name(str(ths.get("name") or ""))
            if key and key not in out:
                out[key] = ths
    return out


def _build_ths_kind(
    *,
    ths_kind: str,
    kind_label: str,
    ths_rows: list[dict],
    kpl_snap: dict[str, Any],
) -> list[dict]:
    """同花顺原始类型页签：仅 THS 行；同名开盘啦仅补字段。"""
    enrich_kind = _THS_TO_KPL_ENRICH.get(ths_kind)
    kpl_map = _kpl_by_name_for_kind(kpl_snap, enrich_kind) if enrich_kind else {}
    # 人气 PlateID 仅作点查码补全，不改变类型归属
    hot_map = _kpl_by_name_for_kind(kpl_snap, "hot") if enrich_kind else {}
    out: list[dict] = []
    for ths in ths_rows:
        if not isinstance(ths, dict):
            continue
        name = str(ths.get("name") or ths.get("id") or "")
        row = _blank_unified(name=name)
        row["origin"] = "ths"
        _apply_ths(row, ths, native=True)
        row["kind"] = ths_kind
        row["kind_label"] = str(ths.get("kind_label") or kind_label)
        row["ths_kind"] = ths_kind
        key = dialect.canonicalize_name(name)
        if key and str(ths.get("node_type") or "") != "branch":
            hit = kpl_map.get(key)
            if hit:
                _apply_kpl(row, hit, native=False)
            hot = hot_map.get(key)
            if hot:
                # 点查优先人气 PlateID，类型仍为同花顺
                code = str(hot.get("code") or "")
                if code:
                    row["kpl_code"] = code
                    row["has_kpl"] = True
                    if "kpl" not in row["sources"]:
                        row["sources"].append("kpl")
                    if hot.get("power") is not None:
                        row["kpl_power"] = hot.get("power")
        out.append(row)
    return out


def _build_kpl_kind(
    *,
    kpl_kind: str,
    kind_label: str,
    kpl_rows: list[dict],
    ths_snap: dict[str, Any],
) -> list[dict]:
    """开盘啦原始类型页签：仅 KPL 行；同名同花顺仅补字段。"""
    # 结构类型与同花顺同名类型对齐；人气仅按名称补字段，不并入同花顺页签
    ths_kind = {v: k for k, v in _THS_TO_KPL_ENRICH.items()}.get(kpl_kind)
    ths_map = _ths_leaf_by_name(ths_snap, ths_kind) if ths_kind else (
        _ths_leaf_by_name(ths_snap) if kpl_kind == "hot" else {}
    )
    out: list[dict] = []
    for cand in kpl_rows:
        if not isinstance(cand, dict):
            continue
        code = str(cand.get("code") or "")
        name = str(cand.get("name") or code)
        row = _blank_unified(name=name)
        row["origin"] = "kpl"
        _apply_kpl(row, cand, native=True)
        row["kind"] = kpl_kind
        row["kind_label"] = kind_label
        row["kpl_kind"] = kpl_kind
        row["kpl_kind_label"] = kind_label
        row["node_type"] = "flat"
        row["tree_path"] = f"{kind_label} › {name}"
        row["parent_id"] = f"__kpl_{kpl_kind}_root__"
        row["depth"] = 1
        key = dialect.canonicalize_name(name)
        if key and ths_map.get(key):
            _apply_ths(row, ths_map[key], native=False)
            row["kind"] = kpl_kind
            row["kind_label"] = kind_label
            row["origin"] = "kpl"
            row["node_type"] = "flat"
            row["tree_path"] = f"{kind_label} › {name}"
            row["parent_id"] = f"__kpl_{kpl_kind}_root__"
            row["depth"] = 1
        out.append(row)
    return out


def build_merged(*, ths_snap: dict[str, Any], kpl_snap: dict[str, Any]) -> dict[str, list[dict]]:
    """分列产出：ths:* 与 kpl:*，互不并入对方类型页签。"""
    merged: dict[str, list[dict]] = {}
    ths_kinds = ths_snap.get("kinds") or {}

    for key, ths_kind, label in THS_KIND_KEYS:
        entry = ths_kinds.get(ths_kind) or {}
        ths_rows = list(entry.get("rows") or []) if isinstance(entry, dict) else []
        merged[key] = _build_ths_kind(
            ths_kind=ths_kind,
            kind_label=label,
            ths_rows=ths_rows,
            kpl_snap=kpl_snap,
        )

    kpl_kinds = kpl_snap.get("kinds") or {}
    for key, kpl_kind, label in KPL_KIND_KEYS:
        entry = kpl_kinds.get(kpl_kind) or {}
        kpl_rows = list(entry.get("rows") or []) if isinstance(entry, dict) else []
        merged[key] = _build_kpl_kind(
            kpl_kind=kpl_kind,
            kind_label=label,
            kpl_rows=kpl_rows,
            ths_snap=ths_snap,
        )

    return merged


def snapshot(*, ensure_kpl: bool = True, force_kpl: bool = False) -> dict[str, Any]:
    """板块管理快照。"""
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
