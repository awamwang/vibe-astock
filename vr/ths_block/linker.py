"""调用本机 ths-linker CLI 获取板块 list / tree。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

_LIST_KINDS = ("custom", "conception", "industry", "region", "daily")
_TREE_KINDS = ("conception", "industry", "region")
_TIMEOUT = 90


def _extract_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    start = text.find("{")
    if start < 0:
        raise RuntimeError(f"ths-linker 未返回 JSON：{text[:200]}")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(obj, dict):
        raise RuntimeError("ths-linker 返回非对象 JSON")
    return obj


def _run(action: str, kind: str, *, ths_dir: str | None = None) -> dict[str, Any]:
    exe = shutil.which("ths-linker")
    if not exe:
        raise RuntimeError("未找到 ths-linker 命令，请先安装并加入 PATH")
    cmd = [exe, "ths-block", action, "--kind", kind, "--json"]
    if ths_dir:
        cmd.extend(["--ths-dir", ths_dir])
    env = os.environ.copy()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ths-linker 超时（{kind}/{action}）") from exc

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


def fetch_list(kind: str, *, ths_dir: str | None = None) -> dict[str, Any]:
    return _run("list", kind, ths_dir=ths_dir)


def fetch_tree(kind: str, *, ths_dir: str | None = None) -> dict[str, Any]:
    return _run("tree", kind, ths_dir=ths_dir)


def is_cli_available() -> bool:
    """ths-linker 是否已在 PATH 中。"""
    return shutil.which("ths-linker") is not None


def list_kinds() -> tuple[str, ...]:
    return _LIST_KINDS


def tree_kinds() -> tuple[str, ...]:
    return _TREE_KINDS
