"""消息关注板块 —— 消息分析目标板块命中筛选。

配置落盘：`~/.duanxian-agents/config/message_follow_blocks.json`
无内置默认，由用户在同花顺板块页维护。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from .util import atomic_write_json

_CONFIG_DIR = os.path.expanduser("~/.duanxian-agents/config")
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "message_follow_blocks.json")
_SCHEMA = 1
_LOCK = threading.Lock()
_BLOCKS: list[dict[str, str]] | None = None

_TARGET_KINDS = frozenset({"sector", "theme"})


class MessageFollowBlockError(ValueError):
    """消息关注板块配置非法。"""


def _norm(raw: str) -> str:
    return str(raw or "").replace(" ", "").replace("\u3000", "").strip()


def _block_key(kind: str, block_id: str) -> tuple[str, str]:
    return (str(kind or "").strip(), str(block_id or "").strip())


def _sanitize_one(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()
    block_id = str(raw.get("id") or "").strip()
    name = _norm(str(raw.get("name") or ""))
    if not kind or not block_id:
        return None
    return {"kind": kind, "id": block_id, "name": name or block_id}


def _sanitize(blocks: object) -> list[dict[str, str]]:
    if not isinstance(blocks, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in blocks:
        cleaned = _sanitize_one(item)
        if not cleaned:
            continue
        key = _block_key(cleaned["kind"], cleaned["id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _read_disk() -> list[dict[str, str]]:
    if not os.path.isfile(_CONFIG_PATH):
        return []
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            env = json.load(fh)
        if not isinstance(env, dict):
            return []
        return _sanitize(env.get("blocks"))
    except Exception:  # noqa: BLE001
        return []


def load_blocks() -> list[dict[str, str]]:
    """读取当前关注板块列表（带进程内缓存）。"""
    global _BLOCKS
    if _BLOCKS is not None:
        return [dict(x) for x in _BLOCKS]
    with _LOCK:
        if _BLOCKS is None:
            _BLOCKS = _read_disk()
        return [dict(x) for x in _BLOCKS]


def reload_blocks() -> list[dict[str, str]]:
    """丢弃缓存并重新读盘。"""
    global _BLOCKS
    with _LOCK:
        _BLOCKS = _read_disk()
        return [dict(x) for x in _BLOCKS]


def save_blocks(blocks: list) -> list[dict[str, str]]:
    """校验并写入关注板块列表，返回清洗后的副本。"""
    cleaned = _sanitize(blocks)
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "blocks": cleaned}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入消息关注板块配置失败：{_CONFIG_PATH}")
    global _BLOCKS
    with _LOCK:
        _BLOCKS = [dict(x) for x in cleaned]
    return [dict(x) for x in cleaned]


def reset_blocks() -> list[dict[str, str]]:
    """清空关注板块列表。"""
    return save_blocks([])


def export_config() -> dict:
    """供 API / 设置页读取。"""
    blocks = load_blocks()
    return {
        "schema": _SCHEMA,
        "blocks": blocks,
        "path": _CONFIG_PATH,
    }


def is_followed(kind: str, block_id: str, blocks: list[dict[str, str]] | None = None) -> bool:
    """判断指定板块是否已关注。"""
    key = _block_key(kind, block_id)
    if not key[0] or not key[1]:
        return False
    src = blocks if blocks is not None else load_blocks()
    return any(_block_key(b["kind"], b["id"]) == key for b in src)


def toggle_block(
    *,
    kind: str,
    block_id: str,
    name: str = "",
    follow: bool | None = None,
) -> list[dict[str, str]]:
    """切换或设定关注状态；follow=None 时取反。"""
    kind_s = str(kind or "").strip()
    id_s = str(block_id or "").strip()
    if not kind_s or not id_s:
        raise MessageFollowBlockError("板块 kind 与 id 不能为空")
    current = load_blocks()
    key = _block_key(kind_s, id_s)
    exists = any(_block_key(b["kind"], b["id"]) == key for b in current)
    want = (not exists) if follow is None else bool(follow)
    if want and exists:
        # 已关注时仅刷新名称
        next_list = []
        for b in current:
            if _block_key(b["kind"], b["id"]) == key:
                next_list.append({
                    "kind": kind_s,
                    "id": id_s,
                    "name": _norm(name) or b.get("name") or id_s,
                })
            else:
                next_list.append(b)
        return save_blocks(next_list)
    if want and not exists:
        return save_blocks([
            *current,
            {"kind": kind_s, "id": id_s, "name": _norm(name) or id_s},
        ])
    if not want and exists:
        return save_blocks([b for b in current if _block_key(b["kind"], b["id"]) != key])
    return current


def _target_fields(raw: Any) -> tuple[str, str, str]:
    if hasattr(raw, "kind"):
        kind = str(getattr(raw, "kind", "") or "")
        code = str(getattr(raw, "code", None) or "")
        name = str(getattr(raw, "name", "") or "")
        return kind, code, name
    if isinstance(raw, dict):
        return (
            str(raw.get("kind") or ""),
            str(raw.get("code") or ""),
            str(raw.get("name") or ""),
        )
    return "", "", ""


def match_in_targets(
    blocks: list[dict[str, str]],
    targets: list[Any] | None,
) -> list[dict[str, str]]:
    """在消息目标中查找命中的关注板块，返回命中列表（保持配置顺序）。"""
    if not blocks or not targets:
        return []
    target_codes: set[str] = set()
    target_names: set[str] = set()
    for t in targets:
        kind, code, name = _target_fields(t)
        if kind and kind not in _TARGET_KINDS:
            continue
        if code.strip():
            target_codes.add(code.strip())
        n = _norm(name)
        if n:
            target_names.add(n)
    if not target_codes and not target_names:
        return []
    out: list[dict[str, str]] = []
    for b in blocks:
        bid = str(b.get("id") or "").strip()
        bname = _norm(b.get("name") or "")
        if (bid and bid in target_codes) or (bname and bname in target_names):
            out.append(dict(b))
    return out


def build_follow_blocks_sql(blocks: list[dict[str, str]]) -> tuple[str, list[str]]:
    """生成「目标板块命中任一关注板块」的 SQL 片段与参数。"""
    if not blocks:
        return "1=0", []
    ids = [str(b["id"]).strip() for b in blocks if str(b.get("id") or "").strip()]
    names = [_norm(b.get("name") or "") for b in blocks if _norm(b.get("name") or "")]
    # 去重保序
    seen_id: set[str] = set()
    uniq_ids: list[str] = []
    for i in ids:
        if i not in seen_id:
            seen_id.add(i)
            uniq_ids.append(i)
    seen_name: set[str] = set()
    uniq_names: list[str] = []
    for n in names:
        if n not in seen_name:
            seen_name.add(n)
            uniq_names.append(n)
    parts: list[str] = []
    args: list[str] = []
    kind_ph = "'sector','theme'"
    if uniq_ids:
        ph = ",".join("?" * len(uniq_ids))
        parts.append(f"(kind IN ({kind_ph}) AND code IN ({ph}))")
        args.extend(uniq_ids)
    if uniq_names:
        ph = ",".join("?" * len(uniq_names))
        parts.append(f"(kind IN ({kind_ph}) AND name IN ({ph}))")
        args.extend(uniq_names)
    if not parts:
        return "1=0", []
    inner = " OR ".join(parts)
    return (
        f"EXISTS (SELECT 1 FROM impact_target WHERE analyzed_id = analyzed_message.id AND ({inner}))",
        args,
    )


# 兼容旧调用名
build_follow_block_sql = build_follow_blocks_sql
