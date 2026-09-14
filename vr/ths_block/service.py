"""同花顺板块缓存刷新与查询。"""

from __future__ import annotations

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from . import cache, linker, persist, stocks, theme_daily, tree as block_tree

_BEIJING = timezone(timedelta(hours=8))
_TREE_KINDS = set(linker.tree_kinds())
_THEME_KIND = linker.theme_kind()
_THEME_ROOT_ID = "__theme_root__"
_BLOCK_CODE_RE = re.compile(r"^[A-Za-z0-9]{3,8}$")
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
    for key in ("query_key", "hex_id", "stock_count", "theme_key", "root_id", "block_type"):
        if key in meta and meta[key] is not None:
            out[key] = meta[key]
    return out


def _is_block_code(value: str) -> bool:
    text = str(value or "").strip()
    if not text or not _BLOCK_CODE_RE.fullmatch(text):
        return False
    return not any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _theme_row_fields(meta: dict[str, Any]) -> dict[str, Any]:
    out = _custom_row_fields(meta)
    for key in ("sort_value", "latest_event_time", "rise_pct", "limit_up_count", "up_count", "down_count"):
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
    theme_key: str | None = None,
    root_id: str | None = None,
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
    if theme_key:
        row["theme_key"] = theme_key
    if root_id:
        row["root_id"] = root_id
    block_type = node.get("block_type")
    if block_type:
        row["block_type"] = str(block_type)
    if node.get("stock_count") is not None:
        row["stock_count"] = node.get("stock_count")
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
                        theme_key=theme_key,
                        root_id=root_id,
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


def _resolve_theme_identity(
    key: str,
    raw: Any,
    *,
    list_source: str,
) -> tuple[str | None, str | None, str, dict[str, Any]]:
    """从主题 list 条目解析 (theme_key, root_id, name, meta)。"""
    meta: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {"name": str(raw or key)}
    name = str(meta.get("name") or key).strip() or key
    root_id = str(meta.get("root_id") or "").strip().upper() or None
    theme_key = str(meta.get("theme_key") or "").strip() or None
    if _is_block_code(key):
        root_id = root_id or key.strip().upper()
    elif not theme_key:
        theme_key = key
    # 在线列表以 theme_key 为键；本地列表以 root_id 为键
    if list_source in ("online", "auto") and not theme_key and not _is_block_code(key):
        theme_key = key
    if not theme_key and name and not _is_block_code(name):
        theme_key = name
    meta.setdefault("name", name)
    meta.setdefault("block_type", "hot-theme")
    if theme_key:
        meta["theme_key"] = theme_key
    if root_id:
        meta["root_id"] = root_id
    return theme_key, root_id, name, meta


def _fetch_one_theme_tree(
    ths_dir: str,
    *,
    theme_key: str | None,
    root_id: str | None,
) -> dict[str, Any]:
    """优先本地 root_id，失败再按 theme_key。"""
    errors: list[str] = []
    if root_id:
        try:
            return linker.fetch_theme_tree(
                ths_dir=ths_dir, root_id=root_id, source="local",
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"local:{exc}")
        try:
            return linker.fetch_theme_tree(
                ths_dir=ths_dir, root_id=root_id, source="auto",
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"auto/root:{exc}")
    if theme_key:
        try:
            return linker.fetch_theme_tree(
                ths_dir=ths_dir, theme_key=theme_key, source="auto",
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"auto/key:{exc}")
    raise RuntimeError("；".join(errors) or "主题树不可用")


def _fetch_theme_kind_entry(ths_dir: str) -> tuple[dict[str, Any], list[str]]:
    """拉取热点主题森林：主题根为 branch，细分为 leaf。"""
    warnings: list[str] = []
    try:
        list_payload = linker.fetch_theme_list(ths_dir=ths_dir, source="local")
    except Exception:  # noqa: BLE001
        list_payload = linker.fetch_theme_list(ths_dir=ths_dir, source="auto")

    list_source = str(list_payload.get("source") or "auto")
    themes_raw = dict(list_payload.get("blocks") or {})
    identities: list[tuple[str | None, str | None, str, dict[str, Any]]] = []
    for key, raw in themes_raw.items():
        identities.append(
            _resolve_theme_identity(str(key), raw, list_source=list_source)
        )

    # 在线热点列表更贴近盘面；本地有 ID 时用 root_id 补全
    if list_source.startswith("local") and identities:
        try:
            online = linker.fetch_theme_list(ths_dir=ths_dir, source="online")
            online_blocks = dict(online.get("blocks") or {})
            if online_blocks:
                # 以在线顺序为主，匹配本地 root
                merged: list[tuple[str | None, str | None, str, dict[str, Any]]] = []
                used_roots: set[str] = set()
                for key, raw in online_blocks.items():
                    tk, rid, name, meta = _resolve_theme_identity(
                        str(key), raw, list_source="online",
                    )
                    # 按名称或 theme_key 对齐本地 root_id
                    hit = None
                    for cand_tk, cand_rid, cand_name, cand_meta in identities:
                        if cand_rid and cand_rid in used_roots:
                            continue
                        if cand_tk and tk and cand_tk == tk:
                            hit = (cand_tk, cand_rid, cand_name, cand_meta)
                            break
                        if cand_name and name and cand_name == name:
                            hit = (cand_tk, cand_rid, cand_name, cand_meta)
                            break
                    if hit and hit[1]:
                        rid = hit[1]
                        used_roots.add(rid)
                        meta = {**hit[3], **meta}
                        meta["root_id"] = rid
                        if tk:
                            meta["theme_key"] = tk
                        merged.append((tk or hit[0], rid, name or hit[2], meta))
                    else:
                        merged.append((tk, rid, name, meta))
                for item in identities:
                    if item[1] and item[1] not in used_roots:
                        merged.append(item)
                identities = merged
                list_source = str(online.get("source") or "online")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"theme: 在线热点列表不可用（{exc}），已使用本地主题")

    blocks_names: dict[str, str] = {}
    blocks_meta: dict[str, dict[str, Any]] = {}
    tree_children: list[dict[str, Any]] = []
    branch_count = 0
    leaf_count = 0
    order_counter = [0]
    rows: list[dict[str, Any]] = []

    # 森林虚拟根
    forest_root = {
        "id": _THEME_ROOT_ID,
        "name": "热点主题",
        "node_type": "branch",
        "block_type": "hot-theme",
        "children": tree_children,
    }
    rows.extend(
        _flatten_tree(
            {
                "id": _THEME_ROOT_ID,
                "name": "热点主题",
                "node_type": "branch",
                "block_type": "hot-theme",
                "children": [],
            },
            kind=_THEME_KIND,
            kind_label="热点主题",
            order_counter=order_counter,
        )
    )

    def _job(item: tuple[str | None, str | None, str, dict[str, Any]]) -> tuple[
        str | None, str | None, str, dict[str, Any], dict[str, Any] | None, str | None
    ]:
        theme_key, root_id, name, meta = item
        try:
            payload = _fetch_one_theme_tree(
                ths_dir, theme_key=theme_key, root_id=root_id,
            )
            return theme_key, root_id, name, meta, payload, None
        except Exception as exc:  # noqa: BLE001
            return theme_key, root_id, name, meta, None, str(exc)

    results: list[
        tuple[str | None, str | None, str, dict[str, Any], dict[str, Any] | None, str | None]
    ] = []
    workers = min(6, max(1, len(identities)))
    if identities:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_job, item) for item in identities]
            for fut in as_completed(futures):
                results.append(fut.result())

    # 保持 identities 原顺序
    by_key = {
        (r[0] or "", r[1] or "", r[2]): r for r in results
    }
    ordered_results = []
    for item in identities:
        key = (item[0] or "", item[1] or "", item[2])
        ordered_results.append(by_key.get(key) or (*item, None, "未返回"))

    for theme_key, root_id, name, meta, payload, err in ordered_results:
        node_id = root_id or theme_key or name
        if not node_id:
            continue
        theme_meta = _theme_row_fields(meta)
        theme_meta["theme_key"] = theme_key or theme_meta.get("theme_key")
        theme_meta["root_id"] = root_id or theme_meta.get("root_id")
        theme_meta["block_type"] = "hot-theme"
        blocks_names[node_id] = name
        blocks_meta[node_id] = theme_meta

        if err or not payload:
            warnings.append(f"theme/{name}: {err or '主题树为空'}")
            # 无树时仍保留主题为 flat，便于列表浏览
            flat_row = {
                "kind": _THEME_KIND,
                "kind_label": "热点主题",
                "id": node_id,
                "name": name,
                "node_type": "flat",
                "tree_path": f"热点主题 › {name}",
                "depth": 1,
                "parent_id": _THEME_ROOT_ID,
                "tree_order": order_counter[0],
                **theme_meta,
            }
            order_counter[0] += 1
            rows.append(flat_row)
            tree_children.append({
                "id": node_id,
                "name": name,
                "node_type": "leaf",
                "block_type": "hot-theme",
                "is_ths_block": True,
                "stock_count": theme_meta.get("stock_count") or 0,
            })
            leaf_count += 1
            continue

        tree = payload.get("tree")
        if not isinstance(tree, dict) or not tree:
            warnings.append(f"theme/{name}: 主题树为空")
            continue

        # 统一根节点身份：优先本地 root_id
        resolved_root = str(payload.get("root_id") or root_id or "").strip().upper()
        resolved_key = (
            str(payload.get("theme_key") or theme_key or "").strip()
            or name
        )
        resolved_name = str(payload.get("root_name") or tree.get("name") or name).strip()
        tree = dict(tree)
        if resolved_root:
            tree["id"] = resolved_root
        elif not tree.get("id"):
            tree["id"] = resolved_key
        tree["name"] = resolved_name
        tree["node_type"] = "branch"
        tree["block_type"] = "hot-theme"
        tree_children.append(tree)

        branch_count += int(payload.get("branch_count") or 0) + 1
        leaf_count += int(payload.get("leaf_count") or 0)

        sub_blocks = payload.get("blocks")
        if isinstance(sub_blocks, dict):
            for bid, brow in sub_blocks.items():
                if not isinstance(brow, dict):
                    continue
                bmeta = _theme_row_fields(brow)
                bmeta["theme_key"] = resolved_key
                if resolved_root:
                    bmeta["root_id"] = resolved_root
                bmeta.setdefault("block_type", "concept-subdivision")
                blocks_names[str(bid)] = str(brow.get("name") or bid)
                blocks_meta[str(bid)] = bmeta

        theme_meta["theme_key"] = resolved_key
        if resolved_root:
            theme_meta["root_id"] = resolved_root
        blocks_names[str(tree.get("id"))] = resolved_name
        blocks_meta[str(tree.get("id"))] = theme_meta

        rows.extend(
            _flatten_tree(
                tree,
                kind=_THEME_KIND,
                kind_label="热点主题",
                path_parts=["热点主题"],
                depth=1,
                parent_id=_THEME_ROOT_ID,
                blocks_names=blocks_names,
                blocks_meta=blocks_meta,
                order_counter=order_counter,
                theme_key=resolved_key,
                root_id=resolved_root or None,
            )
        )

    forest_root["children"] = tree_children
    entry: dict[str, Any] = {
        "kind": _THEME_KIND,
        "kind_label": "热点主题",
        "count": len(blocks_names),
        "blocks": blocks_names,
        "blocks_meta": blocks_meta,
        "root_id": _THEME_ROOT_ID,
        "root_name": "热点主题",
        "branch_count": branch_count + 1,
        "leaf_count": leaf_count,
        "tree": forest_root,
        "tree_mode": "tree",
        "rows": rows,
        "source": list_source,
    }
    return entry, warnings


def _fetch_kind_entry(ths_dir: str, kind: str) -> tuple[dict[str, Any], list[str]]:
    """拉取单个板块类型；树不可用时回退为 flat 列表。"""
    if kind == _THEME_KIND:
        return _fetch_theme_kind_entry(ths_dir)

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
    force: bool = False,
) -> dict[str, Any]:
    kinds_data: dict[str, Any] = dict(snap.get("kinds") or {})
    errors: list[str] = list(snap.get("errors") or [])

    # 热点主题：日限（与开盘啦一致）；非 force 时优先内存今日 / 当日落盘
    if kind == _THEME_KIND and not force:
        existing = kinds_data.get(kind)
        if theme_daily.entry_is_today(existing):
            return {
                "updated_at": snap.get("updated_at") or _now(),
                "ths_dir": snap.get("ths_dir") or ths_dir,
                "kinds": kinds_data,
                "errors": errors,
            }
        archived = theme_daily.load_today()
        if archived and isinstance(archived.get("entry"), dict):
            entry = dict(archived["entry"])
            entry["from_cache"] = True
            entry["fetched_date"] = archived.get("fetched_date")
            kinds_data[kind] = entry
            warnings = [str(w) for w in (archived.get("warnings") or []) if w]
            errors = _merge_errors(errors, kind=kind, new_items=warnings)
            return {
                "updated_at": snap.get("updated_at") or archived.get("updated_at") or _now(),
                "ths_dir": ths_dir or snap.get("ths_dir") or archived.get("ths_dir"),
                "kinds": kinds_data,
                "errors": errors,
            }

    resolved = _resolve_ths_dir(ths_dir or snap.get("ths_dir"))

    try:
        entry, warnings = _fetch_kind_entry(resolved, kind)
        if kind == _THEME_KIND:
            entry = theme_daily.save_today(
                entry, ths_dir=resolved, warnings=warnings,
            )
        kinds_data[kind] = entry
        _maybe_persist_custom_dynamic(
            kind=kind, ths_dir=resolved, entry=entry, warnings=warnings
        )
        errors = _merge_errors(errors, kind=kind, new_items=warnings)
    except Exception as exc:  # noqa: BLE001
        # 主题拉取失败时，若有今日可用日限缓存则降级复用
        if kind == _THEME_KIND:
            archived = theme_daily.load_today()
            if archived and isinstance(archived.get("entry"), dict):
                entry = dict(archived["entry"])
                entry["from_cache"] = True
                kinds_data[kind] = entry
                errors = _merge_errors(
                    errors,
                    kind=kind,
                    new_items=[f"{kind}: {exc}（已使用今日缓存）"],
                )
                return {
                    "updated_at": snap.get("updated_at") or _now(),
                    "ths_dir": resolved,
                    "kinds": kinds_data,
                    "errors": errors,
                }
        errors = _merge_errors(errors, kind=kind, new_items=[f"{kind}: {exc}"])

    return {
        "updated_at": _now(),
        "ths_dir": resolved,
        "kinds": kinds_data,
        "errors": errors,
    }


def refresh_kind(
    *,
    kind: str,
    ths_dir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """刷新单个板块类型并合并进全局缓存；失败时保留该类型旧数据。

    ``force``：热点主题为 True 时忽略日限强制重拉；其它类型忽略该参数。
    """
    global _REFRESH_BUSY
    kind_norm = kind.strip()
    if kind_norm not in linker.list_kinds():
        raise ValueError(f"未知板块类型: {kind_norm}")

    with _REFRESH_LOCK:
        _REFRESH_BUSY += 1
        try:
            snap = cache.get() or {}
            snapshot = _apply_kind_refresh(
                snap, kind_norm, ths_dir=ths_dir, force=force,
            )
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


def refresh_cache(
    *,
    ths_dir: str | None = None,
    force_theme: bool = False,
) -> dict[str, Any]:
    """从 ths-linker 逐类型拉取板块并写入内存缓存；部分失败不影响其它类型。

    ``force_theme``：手动全量刷新时为 True，忽略热点主题日限。
    """
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
                    if kind == _THEME_KIND:
                        partial = _apply_kind_refresh(
                            {
                                "updated_at": snap.get("updated_at"),
                                "ths_dir": resolved,
                                "kinds": kinds_data,
                                "errors": errors,
                            },
                            kind,
                            ths_dir=resolved,
                            force=force_theme,
                        )
                        kinds_data = dict(partial.get("kinds") or kinds_data)
                        errors = list(partial.get("errors") or errors)
                        continue
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


def _hydrate_theme_from_daily(snapshot: dict[str, Any]) -> dict[str, Any]:
    """若内存无今日主题，尝试从日限落盘补齐。"""
    kinds = dict(snapshot.get("kinds") or {})
    existing = kinds.get(_THEME_KIND)
    if theme_daily.entry_is_today(existing):
        return snapshot
    if _kind_has_data(existing) and not theme_daily.entry_is_today(existing):
        # 有旧数据但非今日：仍尝试用今日落盘覆盖
        pass
    archived = theme_daily.load_today()
    if not archived or not isinstance(archived.get("entry"), dict):
        return snapshot
    entry = dict(archived["entry"])
    entry["from_cache"] = True
    kinds[_THEME_KIND] = entry
    out = dict(snapshot)
    out["kinds"] = kinds
    if not out.get("ths_dir") and archived.get("ths_dir"):
        out["ths_dir"] = archived.get("ths_dir")
    return out


def get_snapshot() -> dict[str, Any]:
    data = cache.get()
    if data:
        return _hydrate_theme_from_daily(data)
    hydrated = _hydrate_theme_from_daily(
        {
            "updated_at": None,
            "ths_dir": None,
            "kinds": {},
            "errors": [],
            "empty": True,
            "linker_unavailable": False,
        }
    )
    if _kind_has_data((hydrated.get("kinds") or {}).get(_THEME_KIND)):
        hydrated["empty"] = False
        cache.set_snapshot(hydrated)
    return hydrated


def _map_theme_stocks(raw_stocks: list[Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_stocks or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        market = str(item.get("market_id") or item.get("market") or "").strip()
        name = str(item.get("name") or "").strip()
        row: dict[str, str] = {"code": code, "market": market}
        if name:
            row["name"] = name
        items.append(row)
    return items


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
    if not isinstance(meta, dict):
        meta = {}
    if isinstance(meta, dict):
        code = str(meta.get("code") or "").strip()
        if not name:
            name = str(meta.get("name") or "").strip()
    theme_key = str(meta.get("theme_key") or "").strip() or None
    root_id = str(meta.get("root_id") or "").strip().upper() or None
    block_type = str(meta.get("block_type") or "").strip()
    row_hit: dict[str, Any] | None = None
    for row in kind_entry.get("rows") or []:
        if isinstance(row, dict) and str(row.get("id")) == block_id_norm:
            row_hit = row
            if not name:
                name = str(row.get("name") or "")
            if not code:
                code = str(row.get("code") or "").strip()
            if not theme_key:
                theme_key = str(row.get("theme_key") or "").strip() or None
            if not root_id:
                root_id = str(row.get("root_id") or "").strip().upper() or None
            if not block_type:
                block_type = str(row.get("block_type") or "").strip()
            break

    if kind_norm == _THEME_KIND:
        if block_id_norm == _THEME_ROOT_ID:
            raise ValueError("请选择具体热点主题或细分板块")
        # 主题根：整主题成分；细分叶子：单板块
        parent_id = str((row_hit or {}).get("parent_id") or "").strip()
        is_theme_root = block_type == "hot-theme" or (
            parent_id == _THEME_ROOT_ID
            and str((row_hit or {}).get("node_type") or "") in ("branch", "flat")
        )
        if not root_id and _is_block_code(block_id_norm) and is_theme_root:
            root_id = block_id_norm.upper()
        if not theme_key and not is_theme_root:
            # 叶子可能只用 block_code；用 root_id / 父级 theme_key
            parent_meta = (kind_entry.get("blocks_meta") or {}).get(parent_id) or {}
            if isinstance(parent_meta, dict):
                theme_key = str(parent_meta.get("theme_key") or "").strip() or theme_key
                root_id = str(parent_meta.get("root_id") or "").strip().upper() or root_id
        if not theme_key and not root_id:
            raise RuntimeError(f"主题板块缺少 theme_key/root_id: {block_id_norm}")
        scope = "theme" if is_theme_root else "leaf"
        payload = linker.fetch_theme_stocks(
            ths_dir=ths_dir,
            theme_key=theme_key,
            root_id=root_id,
            block_code=None if scope == "theme" else block_id_norm,
            scope=scope,
            source="auto",
        )
        items = _map_theme_stocks(list(payload.get("stocks") or []))
        if not name:
            name = str(
                payload.get("block_name")
                or payload.get("root_name")
                or payload.get("theme_key")
                or block_id_norm
            )
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

    items = stocks.list_block_stocks(Path(ths_dir), kind=kind_norm, block_id=block_id_norm)
    out = {
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
