"""同花顺板块缓存刷新与查询。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from . import cache, linker, stocks

_BEIJING = timezone(timedelta(hours=8))
_TREE_KINDS = set(linker.tree_kinds())


def _now() -> str:
    return datetime.now(_BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _resolve_ths_dir(explicit: str | None = None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    env = os.environ.get("THS_DIR", "").strip()
    if env:
        return env
    state = Path.home() / ".vibe-astock" / "ths-linker-current.json"
    if state.is_file():
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
            ths_dir = str(data.get("ths_dir") or "").strip()
            if ths_dir:
                return ths_dir
        except (OSError, json.JSONDecodeError):
            pass
    raise RuntimeError(
        "无法定位同花顺目录：请设置环境变量 THS_DIR，或启用 vibe-ths-linker 插件连接同花顺"
    )


def _flatten_tree(
    node: dict[str, Any],
    *,
    kind: str,
    kind_label: str,
    path_parts: list[str] | None = None,
) -> list[dict[str, Any]]:
    parts = list(path_parts or [])
    name = str(node.get("name") or "").strip()
    label = name or str(node.get("id") or "")
    cur_path = parts + [label]
    row: dict[str, Any] = {
        "kind": kind,
        "kind_label": kind_label,
        "id": str(node.get("id") or ""),
        "name": name,
        "node_type": str(node.get("node_type") or "leaf"),
        "tree_path": " › ".join(cur_path),
    }
    rows = [row]
    if node.get("node_type") == "branch":
        for child in node.get("children") or []:
            if isinstance(child, dict):
                rows.extend(
                    _flatten_tree(child, kind=kind, kind_label=kind_label, path_parts=cur_path)
                )
    return rows


def _rows_from_list(kind: str, kind_label: str, blocks: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block_id, name in sorted(blocks.items(), key=lambda x: (x[1], x[0])):
        rows.append({
            "kind": kind,
            "kind_label": kind_label,
            "id": block_id,
            "name": name,
            "node_type": "flat",
            "tree_path": name,
        })
    return rows


def refresh_cache(*, ths_dir: str | None = None) -> dict[str, Any]:
    """从 ths-linker 拉取全部板块类型并写入内存缓存。"""
    resolved = _resolve_ths_dir(ths_dir)
    kinds_data: dict[str, Any] = {}
    errors: list[str] = []

    for kind in linker.list_kinds():
        try:
            list_payload = linker.fetch_list(kind, ths_dir=resolved)
            entry: dict[str, Any] = {
                "kind": list_payload.get("kind") or kind,
                "kind_label": list_payload.get("kind_label") or kind,
                "count": int(list_payload.get("count") or 0),
                "blocks": dict(list_payload.get("blocks") or {}),
            }
            if kind in _TREE_KINDS:
                tree_payload = linker.fetch_tree(kind, ths_dir=resolved)
                tree = tree_payload.get("tree") or {}
                entry["root_id"] = tree_payload.get("root_id")
                entry["root_name"] = tree_payload.get("root_name")
                entry["branch_count"] = tree_payload.get("branch_count")
                entry["leaf_count"] = tree_payload.get("leaf_count")
                entry["tree"] = tree
                entry["rows"] = _flatten_tree(
                    tree,
                    kind=entry["kind"],
                    kind_label=str(entry["kind_label"]),
                ) if isinstance(tree, dict) else []
            else:
                entry["rows"] = _rows_from_list(
                    entry["kind"],
                    str(entry["kind_label"]),
                    entry["blocks"],
                )
            kinds_data[kind] = entry
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{kind}: {exc}")

    if not kinds_data and errors:
        raise RuntimeError("；".join(errors))

    snapshot = {
        "updated_at": _now(),
        "ths_dir": resolved,
        "kinds": kinds_data,
        "errors": errors,
    }
    return cache.set_snapshot(snapshot)


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
    if not name:
        for row in kind_entry.get("rows") or []:
            if isinstance(row, dict) and str(row.get("id")) == block_id_norm:
                name = str(row.get("name") or "")
                break

    items = stocks.list_block_stocks(Path(ths_dir), kind=kind_norm, block_id=block_id_norm)
    return {
        "kind": kind_norm,
        "kind_label": kind_entry.get("kind_label") or kind_norm,
        "block_id": block_id_norm,
        "name": name,
        "count": len(items),
        "stocks": items,
    }
