"""插件键值配置 —— 与注册表同目录，文件名为 plugins.plugin-env。

按插件 id 分节保存 KEY=VALUE。管理页展开编辑；启用前写入进程环境，
已填写的项优先于插件目录 .env。
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FILE_NAME = "plugins.plugin-env"
_MAX_VALUE = 8000


def env_file() -> str:
    """用户目录下的插件键值文件，与 plugins.json 同级。"""
    from . import plugin_store as ps

    return os.path.join(ps._USER_DIR, _FILE_NAME)


def _check_id(plugin_id: str) -> str:
    pid = (plugin_id or "").strip()
    if not _ID_RE.fullmatch(pid):
        raise ValueError(f"插件 id 无效：{plugin_id!r}")
    return pid


def _unescape(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            mapped = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"'}.get(nxt)
            if mapped is None:
                out.append(nxt)
            else:
                out.append(mapped)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            return _unescape(inner)
        return inner
    return value


def load_all() -> dict[str, dict[str, str]]:
    """读出全部分节。文件缺失或损坏行跳过，不抛给调用方。"""
    path = env_file()
    try:
        text = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        return {}
    except OSError:
        return {}

    sections: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]") and len(line) >= 3:
            name = line[1:-1].strip()
            if _ID_RE.fullmatch(name):
                current = name
                sections.setdefault(current, {})
            else:
                current = None
            continue
        if current is None or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not _KEY_RE.fullmatch(key):
            continue
        sections[current][key] = _parse_value(value)
    return sections


def load_section(plugin_id: str) -> dict[str, str]:
    """该插件已保存的键值；尚未写入过则返回空 dict。"""
    pid = _check_id(plugin_id)
    return dict(load_all().get(pid) or {})


def section_exists(plugin_id: str) -> bool:
    pid = _check_id(plugin_id)
    return pid in load_all()


def _quote(value: str) -> str:
    if value == "" or any(ch in value for ch in " \t#\"'\\$\n\r"):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    return value


def _dump(sections: dict[str, dict[str, str]]) -> str:
    lines = ["# 插件键值配置，按插件 id 分节。与 plugins.json 同目录。", ""]
    for pid, values in sections.items():
        lines.append(f"[{pid}]")
        for key, value in values.items():
            lines.append(f"{key}={_quote(value)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _clean_values(values: dict) -> dict[str, str]:
    if not isinstance(values, dict):
        raise ValueError("env 须为键值对象")
    cleaned: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key).strip()
        if not key:
            continue
        if not _KEY_RE.fullmatch(key):
            raise ValueError(f"配置键无效：{key}")
        if not isinstance(raw_value, str):
            raise ValueError(f"{key} 的值须为字符串")
        if len(raw_value) > _MAX_VALUE:
            raise ValueError(f"{key} 过长")
        if key in cleaned:
            raise ValueError(f"配置键重复：{key}")
        cleaned[key] = raw_value
    return cleaned


def save_section(plugin_id: str, values: dict) -> dict[str, str]:
    """替换该插件一节并落盘，其它插件的节保持不变。"""
    pid = _check_id(plugin_id)
    cleaned = _clean_values(values)
    sections = load_all()
    sections[pid] = cleaned
    _atomic_write(env_file(), _dump(sections))
    return cleaned


def delete_section(plugin_id: str) -> None:
    """卸载插件时去掉对应分节；没有其它节则删除文件。"""
    try:
        pid = _check_id(plugin_id)
    except ValueError:
        return
    sections = load_all()
    if pid not in sections:
        return
    sections.pop(pid, None)
    path = env_file()
    if not sections:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        return
    _atomic_write(path, _dump(sections))


def apply_to_environ(plugin_id: str) -> None:
    """启用前把已保存的非空项写入进程环境；留空的项从环境里去掉，便于回落到默认或 .env。"""
    try:
        pid = _check_id(plugin_id)
    except ValueError:
        return
    sections = load_all()
    if pid not in sections:
        return
    for key, value in sections[pid].items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def _fields_public(fields: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in fields or ():
        key = str(getattr(field, "key", "") or "").strip()
        if not key or key in seen or not _KEY_RE.fullmatch(key):
            continue
        seen.add(key)
        out.append({
            "key": key,
            "label": str(getattr(field, "label", "") or key),
            "hint": str(getattr(field, "hint", "") or ""),
            "secret": bool(getattr(field, "secret", False)),
            "default": str(getattr(field, "default", "") or ""),
        })
    return out


def _probe_fields(path: str) -> tuple:
    from .hooks import _unload_module, load_pack_from_path

    probe_id = f"envprobe{uuid.uuid4().hex[:8]}"
    try:
        pack = load_pack_from_path(path, plugin_id=probe_id)
        return tuple(getattr(pack, "env_fields", ()) or ())
    finally:
        _unload_module(probe_id)


def describe(plugin_id: str, path: str) -> dict[str, Any]:
    """给管理页：声明的配置项 + 已保存的键值。读声明失败时仍返回已保存内容。"""
    from .hooks import PLUGINS

    pid = _check_id(plugin_id)
    loaded = next((lp for lp in PLUGINS if lp.id == pid), None)
    error = ""
    if loaded is not None:
        fields = tuple(getattr(loaded.pack, "env_fields", ()) or ())
    else:
        try:
            fields = _probe_fields(path)
        except Exception as exc:  # noqa: BLE001
            fields = ()
            error = f"{type(exc).__name__}: {exc}"
    return {
        "plugin": pid,
        "file": env_file(),
        "fields": _fields_public(fields),
        "env": load_section(pid),
        "error": error,
    }
