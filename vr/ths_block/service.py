"""同花顺板块缓存刷新与查询。"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from . import cache, linker, persist, stocks, tree as block_tree

_BEIJING = timezone(timedelta(hours=8))
_TREE_KINDS = set(linker.tree_kinds())
_REFRESH_LOCK = threading.Lock()
_REFRESH_BUSY = 0
_LINKER_MSG = "依赖于第三方工具，目前无法请求"
_LINKER_ERROR_MARKERS = (
    "ths-linker",
    "未找到",
    "超时",
    "退出码",
    "未返回 json",
    "无法定位同花顺",
    "返回失败",
)


def _now() -> str:
    return datetime.now(_BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def is_refresh_busy() -> bool:
    """是否有板块刷新正在进行（含 ths-linker 调用）。"""
    return _REFRESH_BUSY > 0


def linker_unavailable() -> bool:
    """第三方 ths-linker 不可用且当前无可用板块缓存。"""
    snap = cache.get()
    if not snap:
        return False
    return bool(snap.get("linker_unavailable"))


def _kind_has_data(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    blocks = entry.get("blocks")
    if isinstance(blocks, dict) and blocks:
        return True
    rows = entry.get("rows")
    return isinstance(rows, list) and bool(rows)


def _has_any_kind_data(kinds: dict[str, Any]) -> bool:
    for kind in linker.list_kinds():
        if _kind_has_data(kinds.get(kind)):
            return True
    return False


def _is_linker_error_text(text: str) -> bool:
    t = str(text or "").lower()
    return any(m in t for m in _LINKER_ERROR_MARKERS)


def _apply_linker_status(snapshot: dict[str, Any]) -> dict[str, Any]:
    kinds = snapshot.get("kinds") or {}
    if _has_any_kind_data(kinds):
        snapshot["linker_unavailable"] = False
        snapshot.pop("linker_message", None)
        return snapshot
    errors = snapshot.get("errors") or []
    if errors and all(_is_linker_error_text(e) for e in errors):
        snapshot["linker_unavailable"] = True
        snapshot["linker_message"] = _LINKER_MSG
    elif snapshot.get("linker_unavailable"):
        snapshot["linker_message"] = snapshot.get("linker_message") or _LINKER_MSG
    else:
        snapshot["linker_unavailable"] = False
        snapshot.pop("linker_message", None)
    return snapshot


def ensure_linker_cli_or_mark_unavailable() -> bool:
    """若 ths-linker 不在 PATH 且尚无板块数据，标记为不可用。"""
    if linker.is_cli_available():
        return True
    snap = cache.get() or {}
    if _has_any_kind_data(snap.get("kinds") or {}):
        return True
    snapshot = _apply_linker_status(
        {
            "updated_at": _now(),
            "ths_dir": snap.get("ths_dir"),
            "kinds": dict(snap.get("kinds") or {}),
            "errors": ["linker: 未找到 ths-linker 命令，请先安装并加入 PATH"],
        }
    )
    cache.set_snapshot(snapshot)
    return False


def _resolve_ths_dir(explicit: str | None = None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    env = os.environ.get("THS_DIR", "").strip()
    if env:
        return env
    try:
        from duanxian import current_stock as cs

        ths_dir = cs.load_legacy_ths_dir()
        if ths_dir:
            return ths_dir
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError(
        "无法定位同花顺目录：请设置环境变量 THS_DIR，或启用 vibe-ths-linker 插件连接同花顺"
    )


def _normalize_blocks(
    blocks: dict[str, Any],
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """将 list 返回的 blocks 规范为 id→名称 与 id→扩展元数据。"""
    names: dict[str, str] = {}
    meta: dict[str, dict[str, Any]] = {}
    for block_id, raw in (blocks or {}).items():
        bid = str(block_id)
        if isinstance(raw, dict):
            names[bid] = str(raw.get("name") or "").strip()
            meta[bid] = dict(raw)
        else:
            names[bid] = str(raw or "").strip()
    return names, meta


def _custom_row_fields(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    custom_type = meta.get("custom_type")
    if custom_type:
        out["custom_type"] = str(custom_type)
    dynamic_kind = meta.get("dynamic_kind")
    if dynamic_kind:
        out["dynamic_kind"] = str(dynamic_kind)
    code = meta.get("code")
    if code not in (None, ""):
        out["code"] = str(code).strip()
    for key in ("query_key", "hex_id", "stock_count"):
        if key in meta and meta[key] is not None:
            out[key] = meta[key]
    return out


def _enrich_leaf_row(
    row: dict[str, Any],
    *,
    blocks_names: dict[str, str] | None,
    blocks_meta: dict[str, dict[str, Any]] | None,
) -> None:
    """用 list 接口的 blocks / blocks_meta 补全树叶子节点的名称与扩展字段。"""
    if row.get("node_type") == "branch":
        return
    bid = str(row.get("id") or "")
    if blocks_names and not row.get("name"):
        row["name"] = str(blocks_names.get(bid) or "").strip()
    if blocks_meta and bid in blocks_meta:
        row.update(_custom_row_fields(blocks_meta[bid]))


def _flatten_tree(
    node: dict[str, Any],
    *,
    kind: str,
    kind_label: str,
    path_parts: list[str] | None = None,
    depth: int = 0,
    parent_id: str | None = None,
    blocks_names: dict[str, str] | None = None,
    blocks_meta: dict[str, dict[str, Any]] | None = None,
    order_counter: list[int] | None = None,
) -> list[dict[str, Any]]:
    parts = list(path_parts or [])
    name = str(node.get("name") or "").strip()
    label = name or str(node.get("id") or "")
    cur_path = parts + [label]
    node_id = str(node.get("id") or "")
    node_type = str(node.get("node_type") or "leaf")
    if order_counter is None:
        order_counter = [0]
    row: dict[str, Any] = {
        "kind": kind,
        "kind_label": kind_label,
        "id": node_id,
        "name": name,
        "node_type": node_type,
        "tree_path": " › ".join(cur_path),
        "depth": depth,
        "parent_id": parent_id,
        "tree_order": order_counter[0],
    }
    order_counter[0] += 1
    _enrich_leaf_row(row, blocks_names=blocks_names, blocks_meta=blocks_meta)
    rows = [row]
    if node_type == "branch":
        for child in node.get("children") or []:
            if isinstance(child, dict):
                rows.extend(
                    _flatten_tree(
                        child,
                        kind=kind,
                        kind_label=kind_label,
                        path_parts=cur_path,
                        depth=depth + 1,
                        parent_id=node_id or None,
                        blocks_names=blocks_names,
                        blocks_meta=blocks_meta,
                        order_counter=order_counter,
                    )
                )
    return rows


def _rows_from_list(
    kind: str,
    kind_label: str,
    blocks: dict[str, str],
    *,
    blocks_meta: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    meta_map = blocks_meta or {}
    for block_id, name in sorted(blocks.items(), key=lambda x: (x[1], x[0])):
        row: dict[str, Any] = {
            "kind": kind,
            "kind_label": kind_label,
            "id": block_id,
            "name": name,
            "node_type": "flat",
            "tree_path": name,
        }
        if kind == "custom" or block_id in meta_map:
            row.update(_custom_row_fields(meta_map.get(block_id) or {}))
        rows.append(row)
    return rows


def _fetch_kind_entry(ths_dir: str, kind: str) -> tuple[dict[str, Any], list[str]]:
    """拉取单个板块类型；树不可用时回退为 flat 列表。"""
    warnings: list[str] = []
    list_payload = linker.fetch_list(kind, ths_dir=ths_dir)
    blocks_raw = dict(list_payload.get("blocks") or {})
    blocks_names, blocks_meta = _normalize_blocks(blocks_raw)

    entry: dict[str, Any] = {
        "kind": list_payload.get("kind") or kind,
        "kind_label": list_payload.get("kind_label") or kind,
        "count": int(list_payload.get("count") or len(blocks_names)),
        "blocks": blocks_names,
    }
    if blocks_meta:
        entry["blocks_meta"] = blocks_meta

    kind_key = str(entry["kind"])
    kind_label = str(entry["kind_label"])

    if kind in _TREE_KINDS:
        try:
            tree_result = block_tree.build_block_tree(
                ths_dir, kind_key, names=blocks_names
            )
            tree = tree_result.get("tree")
            if not isinstance(tree, dict) or not tree:
                raise RuntimeError("板块树为空")
            entry["root_id"] = tree_result.get("root_id")
            entry["root_name"] = tree_result.get("root_name")
            entry["branch_count"] = tree_result.get("branch_count")
            entry["leaf_count"] = tree_result.get("leaf_count")
            entry["tree"] = tree
            entry["tree_mode"] = "tree"
            entry["rows"] = _flatten_tree(
                tree,
                kind=kind_key,
                kind_label=kind_label,
                blocks_names=blocks_names,
                blocks_meta=blocks_meta,
            )
        except Exception as local_exc:  # noqa: BLE001
            try:
                tree_payload = linker.fetch_tree(kind, ths_dir=ths_dir)
                tree = tree_payload.get("tree")
                if not isinstance(tree, dict) or not tree:
                    raise RuntimeError("板块树为空")
                entry["root_id"] = tree_payload.get("root_id")
                entry["root_name"] = tree_payload.get("root_name")
                entry["branch_count"] = tree_payload.get("branch_count")
                entry["leaf_count"] = tree_payload.get("leaf_count")
                entry["tree"] = tree
                entry["tree_mode"] = "tree"
                entry["rows"] = _flatten_tree(
                    tree,
                    kind=kind_key,
                    kind_label=kind_label,
                    blocks_names=blocks_names,
                    blocks_meta=blocks_meta,
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(
                    f"{kind}: 树结构不可用（{local_exc}；ths-linker: {exc}），已使用 flat 列表"
                )
                entry["tree_mode"] = "flat_fallback"
                entry["rows"] = _rows_from_list(
                    kind_key,
                    kind_label,
                    blocks_names,
                    blocks_meta=blocks_meta,
                )
    else:
        entry["rows"] = _rows_from_list(
            kind_key,
            kind_label,
            blocks_names,
            blocks_meta=blocks_meta,
        )

    return entry, warnings


def _merge_errors(existing: list[str], *, kind: str, new_items: list[str]) -> list[str]:
    kept = [e for e in existing if not e.startswith(f"{kind}:")]
    return kept + new_items


def _maybe_persist_custom_dynamic(
    *,
    kind: str,
    ths_dir: str,
    entry: dict[str, Any] | None,
    warnings: list[str],
) -> None:
    if kind != "custom" or not entry:
        return
    try:
        persist.save_dynamic_custom_blocks(ths_dir=ths_dir, entry=entry)
    except OSError as exc:
        warnings.append(f"custom: 动态板块落盘失败（{exc}）")


def _apply_kind_refresh(
    snap: dict[str, Any],
    kind: str,
    *,
    ths_dir: str | None = None,
) -> dict[str, Any]:
    resolved = _resolve_ths_dir(ths_dir or snap.get("ths_dir"))
    kinds_data: dict[str, Any] = dict(snap.get("kinds") or {})
    errors: list[str] = list(snap.get("errors") or [])

    try:
        entry, warnings = _fetch_kind_entry(resolved, kind)
        kinds_data[kind] = entry
        _maybe_persist_custom_dynamic(
            kind=kind, ths_dir=resolved, entry=entry, warnings=warnings
        )
        errors = _merge_errors(errors, kind=kind, new_items=warnings)
    except Exception as exc:  # noqa: BLE001
        errors = _merge_errors(errors, kind=kind, new_items=[f"{kind}: {exc}"])

    return {
        "updated_at": _now(),
        "ths_dir": resolved,
        "kinds": kinds_data,
        "errors": errors,
    }


def refresh_kind(*, kind: str, ths_dir: str | None = None) -> dict[str, Any]:
    """刷新单个板块类型并合并进全局缓存；失败时保留该类型旧数据。"""
    global _REFRESH_BUSY
    kind_norm = kind.strip()
    if kind_norm not in linker.list_kinds():
        raise ValueError(f"未知板块类型: {kind_norm}")

    with _REFRESH_LOCK:
        _REFRESH_BUSY += 1
        try:
            snap = cache.get() or {}
            snapshot = _apply_kind_refresh(snap, kind_norm, ths_dir=ths_dir)
            snapshot = _apply_linker_status(snapshot)
            snapshot = cache.set_snapshot(snapshot)
        finally:
            _REFRESH_BUSY -= 1
    try:
        from .processor import invalidate_name_index, mark_kind_cached

        invalidate_name_index()
        mark_kind_cached(kind_norm)
    except Exception:  # noqa: BLE001
        pass
    return snapshot


def refresh_cache(*, ths_dir: str | None = None) -> dict[str, Any]:
    """从 ths-linker 逐类型拉取板块并写入内存缓存；部分失败不影响其它类型。"""
    global _REFRESH_BUSY
    with _REFRESH_LOCK:
        _REFRESH_BUSY += 1
        try:
            resolved = _resolve_ths_dir(ths_dir)
            snap = cache.get() or {}
            kinds_data: dict[str, Any] = dict(snap.get("kinds") or {})
            errors: list[str] = []

            for kind in linker.list_kinds():
                try:
                    entry, warnings = _fetch_kind_entry(resolved, kind)
                    kinds_data[kind] = entry
                    _maybe_persist_custom_dynamic(
                        kind=kind, ths_dir=resolved, entry=entry, warnings=warnings
                    )
                    errors.extend(warnings)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{kind}: {exc}")

            snapshot = _apply_linker_status(
                {
                    "updated_at": _now(),
                    "ths_dir": resolved,
                    "kinds": kinds_data,
                    "errors": errors,
                }
            )
            snapshot = cache.set_snapshot(snapshot)
        finally:
            _REFRESH_BUSY -= 1
    try:
        from .processor import invalidate_name_index, mark_all_kinds_cached

        invalidate_name_index()
        mark_all_kinds_cached()
    except Exception:  # noqa: BLE001
        pass
    return snapshot


def get_snapshot() -> dict[str, Any]:
    data = cache.get()
    if data:
        return data
    return {
        "updated_at": None,
        "ths_dir": None,
        "kinds": {},
        "errors": [],
        "empty": True,
        "linker_unavailable": False,
    }


def get_block_stocks(*, kind: str, block_id: str) -> dict[str, Any]:
    snap = cache.get()
    if not snap or not snap.get("ths_dir"):
        raise RuntimeError("板块缓存为空，请先点击刷新")
    ths_dir = str(snap["ths_dir"])
    kind_norm = kind.strip()
    block_id_norm = block_id.strip()
    kinds = snap.get("kinds") or {}
    kind_entry = kinds.get(kind_norm)
    if not kind_entry:
        raise ValueError(f"未知板块类型: {kind_norm}")

    name = str((kind_entry.get("blocks") or {}).get(block_id_norm) or "")
    code = ""
    meta = (kind_entry.get("blocks_meta") or {}).get(block_id_norm)
    if isinstance(meta, dict):
        code = str(meta.get("code") or "").strip()
        if not name:
            name = str(meta.get("name") or "").strip()
    if not name or not code:
        for row in kind_entry.get("rows") or []:
            if isinstance(row, dict) and str(row.get("id")) == block_id_norm:
                if not name:
                    name = str(row.get("name") or "")
                if not code:
                    code = str(row.get("code") or "").strip()
                break

    items = stocks.list_block_stocks(Path(ths_dir), kind=kind_norm, block_id=block_id_norm)
    out: dict[str, Any] = {
        "kind": kind_norm,
        "kind_label": kind_entry.get("kind_label") or kind_norm,
        "block_id": block_id_norm,
        "name": name,
        "count": len(items),
        "stocks": items,
    }
    if code:
        out["code"] = code
    return out
