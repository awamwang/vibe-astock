"""插件注册表 —— 多插件路径与启用状态，存于用户目录。"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import atomic_write_json, china_now

_USER_DIR = os.path.expanduser("~/.vibe-astock")
_REGISTRY_FILE = os.path.join(_USER_DIR, "plugins.json")
_SCHEMA = 1


@dataclass(frozen=True)
class PluginRecord:
    id: str
    path: str
    name: str
    version: str
    enabled: bool
    registered_at: str


def _default_registry() -> dict:
    return {"schema": _SCHEMA, "plugins": []}


def _registry_path() -> str:
    return _REGISTRY_FILE


def load_registry() -> dict:
    path = _registry_path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or data.get("schema") != _SCHEMA:
            return _default_registry()
        plugins = data.get("plugins")
        if not isinstance(plugins, list):
            return _default_registry()
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _default_registry()


def save_registry(data: dict) -> None:
    os.makedirs(_USER_DIR, exist_ok=True)
    data = dict(data)
    data["schema"] = _SCHEMA
    if not atomic_write_json(_registry_path(), data):
        raise RuntimeError("插件注册表写入失败")


def _to_record(raw: dict) -> PluginRecord | None:
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get("id") or "").strip()
    path = str(raw.get("path") or "").strip()
    if not pid or not path:
        return None
    return PluginRecord(
        id=pid,
        path=path,
        name=str(raw.get("name") or pid),
        version=str(raw.get("version") or ""),
        enabled=bool(raw.get("enabled", True)),
        registered_at=str(raw.get("registered_at") or ""),
    )


def list_plugins(*, include_disabled: bool = True) -> list[PluginRecord]:
    data = load_registry()
    out: list[PluginRecord] = []
    for raw in data.get("plugins") or []:
        rec = _to_record(raw)
        if rec is None:
            continue
        if include_disabled or rec.enabled:
            out.append(rec)
    return out


def list_enabled_paths() -> list[tuple[str, str]]:
    """返回 (plugin_id, absolute_path) 列表，仅已启用且文件仍存在。"""
    rows: list[tuple[str, str]] = []
    for rec in list_plugins(include_disabled=False):
        p = Path(rec.path).expanduser().resolve()
        if p.is_file():
            rows.append((rec.id, str(p)))
        else:
            print(f"⚠️ 插件 {rec.name!r}（{rec.id}）文件不存在，已跳过：{p}")
    return rows


def _new_id(existing: set[str]) -> str:
    while True:
        pid = uuid.uuid4().hex[:8]
        if pid not in existing:
            return pid


def resolve_id(name_or_id: str) -> str:
    """按完整 id 或 id 前缀 / 唯一 name 解析。"""
    key = (name_or_id or "").strip()
    if not key:
        raise ValueError("请提供插件 id 或名称")
    all_recs = list_plugins()
    exact = [r for r in all_recs if r.id == key]
    if len(exact) == 1:
        return exact[0].id
    prefix = [r for r in all_recs if r.id.startswith(key)]
    if len(prefix) == 1:
        return prefix[0].id
    by_name = [r for r in all_recs if r.name == key]
    if len(by_name) == 1:
        return by_name[0].id
    if len(prefix) > 1:
        raise ValueError(f"id 前缀 {key!r} 匹配多个插件，请写更长的 id")
    if len(by_name) > 1:
        raise ValueError(f"名称 {key!r} 对应多个插件，请用 id")
    raise ValueError(f"未找到插件：{key!r}")


def register(path: str, *, enabled: bool = True) -> PluginRecord:
    """注册插件；path 须为含 PACK 的 .py 文件。"""
    from .hooks import load_pack_from_path

    src = Path(path).expanduser()
    if not src.is_file():
        raise ValueError(f"插件文件不存在：{src}")
    if src.suffix.lower() != ".py":
        raise ValueError("插件须为 .py 文件")
    abs_path = str(src.resolve())
    pack = load_pack_from_path(abs_path, plugin_id="probe")

    data = load_registry()
    plugins: list[dict] = list(data.get("plugins") or [])
    for raw in plugins:
        if str(raw.get("path") or "").strip() == abs_path:
            raise ValueError(f"该路径已注册：{abs_path}（id={raw.get('id')}）")

    ids = {str(p.get("id") or "") for p in plugins}
    pid = _new_id(ids)
    rec = PluginRecord(
        id=pid,
        path=abs_path,
        name=pack.name,
        version=pack.version,
        enabled=enabled,
        registered_at=china_now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    plugins.append({
        "id": rec.id,
        "path": rec.path,
        "name": rec.name,
        "version": rec.version,
        "enabled": rec.enabled,
        "registered_at": rec.registered_at,
    })
    save_registry({**data, "plugins": plugins})
    return rec


def uninstall(name_or_id: str) -> PluginRecord:
    pid = resolve_id(name_or_id)
    data = load_registry()
    plugins: list[dict] = list(data.get("plugins") or [])
    hit = None
    kept: list[dict] = []
    for raw in plugins:
        if str(raw.get("id") or "") == pid:
            hit = _to_record(raw)
        else:
            kept.append(raw)
    if hit is None:
        raise ValueError(f"未找到插件：{pid}")
    save_registry({**data, "plugins": kept})
    return hit


def set_enabled(name_or_id: str, enabled: bool) -> PluginRecord:
    pid = resolve_id(name_or_id)
    data = load_registry()
    plugins: list[dict] = list(data.get("plugins") or [])
    hit: PluginRecord | None = None
    for raw in plugins:
        if str(raw.get("id") or "") == pid:
            raw["enabled"] = enabled
            hit = _to_record(raw)
        else:
            pass
    if hit is None:
        raise ValueError(f"未找到插件：{pid}")
    save_registry({**data, "plugins": plugins})
    return hit


def registry_file() -> str:
    return _registry_path()


def override_registry_dir(tmp_dir: str | None) -> None:
    """测试用：重定向注册表目录。"""
    global _USER_DIR, _REGISTRY_FILE
    if tmp_dir is None:
        _USER_DIR = os.path.expanduser("~/.vibe-astock")
    else:
        _USER_DIR = tmp_dir
    _REGISTRY_FILE = os.path.join(_USER_DIR, "plugins.json")
