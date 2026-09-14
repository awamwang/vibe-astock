"""调用本机 ths-linker CLI 获取板块 list / tree / 热点主题。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

_LIST_KINDS = ("custom", "conception", "industry", "region", "daily", "theme")
_TREE_KINDS = ("conception", "industry", "region")
_THEME_KIND = "theme"
_TIMEOUT = 90
_THEME_TIMEOUT = 120


def _extract_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    start = text.find("{")
    if start < 0:
        raise RuntimeError(f"ths-linker 未返回 JSON：{text[:200]}")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(obj, dict):
        raise RuntimeError("ths-linker 返回非对象 JSON")
    return obj


def _run_cli(
    cmd: list[str],
    *,
    timeout: int,
    label: str,
) -> dict[str, Any]:
    exe = shutil.which("ths-linker")
    if not exe:
        raise RuntimeError("未找到 ths-linker 命令，请先安装并加入 PATH")
    full = [exe, *cmd]
    env = os.environ.copy()
    try:
        proc = subprocess.run(
            full,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ths-linker 超时（{label}）") from exc

    payload: dict[str, Any] | None = None
    if (proc.stdout or "").strip():
        try:
            payload = _extract_json(proc.stdout)
        except RuntimeError:
            payload = None

    if payload is not None:
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("error") or "ths-linker 返回失败"))
        return payload

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:500]
        raise RuntimeError(err or f"ths-linker 退出码 {proc.returncode}")
    raise RuntimeError("ths-linker 无有效输出")


def _run(action: str, kind: str, *, ths_dir: str | None = None) -> dict[str, Any]:
    cmd = ["ths-block", action, "--kind", kind, "--json"]
    if ths_dir:
        cmd.extend(["--ths-dir", ths_dir])
    return _run_cli(cmd, timeout=_TIMEOUT, label=f"{kind}/{action}")


def fetch_list(kind: str, *, ths_dir: str | None = None) -> dict[str, Any]:
    return _run("list", kind, ths_dir=ths_dir)


def fetch_tree(kind: str, *, ths_dir: str | None = None) -> dict[str, Any]:
    return _run("tree", kind, ths_dir=ths_dir)


def _theme_cmd(
    action: str,
    *,
    ths_dir: str | None = None,
    theme_key: str | None = None,
    root_id: str | None = None,
    block_code: str | None = None,
    scope: str | None = None,
    source: str = "auto",
    tab: str | None = None,
    include_names: bool = True,
) -> dict[str, Any]:
    cmd = ["ths-theme", action, "--json", "--source", source]
    if ths_dir:
        cmd.extend(["--ths-dir", ths_dir])
    if theme_key:
        cmd.extend(["--theme-key", theme_key])
    if root_id:
        cmd.extend(["--root-id", root_id])
    if block_code:
        cmd.extend(["--block-code", block_code])
    if scope:
        cmd.extend(["--scope", scope])
    if tab:
        cmd.extend(["--tab", tab])
    if action in ("stocks", "full") and not include_names:
        cmd.append("--no-names")
    label = f"theme/{action}"
    if theme_key:
        label = f"{label}/{theme_key}"
    elif root_id:
        label = f"{label}/{root_id}"
    return _run_cli(cmd, timeout=_THEME_TIMEOUT, label=label)


def fetch_theme_list(
    *,
    ths_dir: str | None = None,
    source: str = "auto",
    tab: str = "all",
) -> dict[str, Any]:
    """列出热点主题（不带 theme_key / root_id）。"""
    return _theme_cmd("list", ths_dir=ths_dir, source=source, tab=tab)


def fetch_theme_tree(
    *,
    ths_dir: str | None = None,
    theme_key: str | None = None,
    root_id: str | None = None,
    source: str = "auto",
) -> dict[str, Any]:
    """返回单个热点主题的细分板块树。"""
    if not theme_key and not root_id:
        raise ValueError("fetch_theme_tree 需要 theme_key 或 root_id")
    return _theme_cmd(
        "tree",
        ths_dir=ths_dir,
        theme_key=theme_key,
        root_id=root_id,
        source=source,
    )


def fetch_theme_stocks(
    *,
    ths_dir: str | None = None,
    theme_key: str | None = None,
    root_id: str | None = None,
    block_code: str | None = None,
    scope: str = "leaf",
    source: str = "auto",
    include_names: bool = True,
) -> dict[str, Any]:
    """返回主题 / 细分板块成分股。"""
    if scope == "leaf" and not block_code:
        raise ValueError("stocks scope=leaf 时缺少 block_code")
    if not theme_key and not root_id:
        raise ValueError("fetch_theme_stocks 需要 theme_key 或 root_id")
    return _theme_cmd(
        "stocks",
        ths_dir=ths_dir,
        theme_key=theme_key,
        root_id=root_id,
        block_code=block_code,
        scope=scope,
        source=source,
        include_names=include_names,
    )


def is_cli_available() -> bool:
    """ths-linker 是否已在 PATH 中。"""
    return shutil.which("ths-linker") is not None


def list_kinds() -> tuple[str, ...]:
    return _LIST_KINDS


def tree_kinds() -> tuple[str, ...]:
    return _TREE_KINDS


def theme_kind() -> str:
    return _THEME_KIND
