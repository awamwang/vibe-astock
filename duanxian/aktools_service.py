"""本进程托管的 AKTools HTTP 服务（默认 127.0.0.1:8988）。

`server.py` 启动时 ensure；端口已被占用则复用，不二次拉起。
环境变量：
- `AKTOOLS_HOST` / `AKTOOLS_PORT`：监听地址（默认 127.0.0.1 / 8988）
- `AKTOOLS_MANAGED=0`：禁止本进程自动拉起（仍可连外部已启动的实例）
- `AKTOOLS_KEEP_ALIVE=1`：进程退出时不杀子进程（开发热重载时默认打开）
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Any, Optional

from . import aktools_client as akc

_LOCK = threading.Lock()
_PROC: Optional[subprocess.Popen] = None
_OWNED = False


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def managed_enabled() -> bool:
    return _env_flag("AKTOOLS_MANAGED", True)


def keep_alive() -> bool:
    # 热重载时 worker 反复启停；默认不杀 AKTools，避免每次改代码都重拉子进程
    reload = _env_flag("VIBE_RELOAD", False)
    return _env_flag("AKTOOLS_KEEP_ALIVE", default=reload)


def listen_host() -> str:
    return (os.environ.get("AKTOOLS_HOST") or "127.0.0.1").strip() or "127.0.0.1"


def listen_port() -> int:
    try:
        return int(os.environ.get("AKTOOLS_PORT") or "8988")
    except (TypeError, ValueError):
        return 8988


def _sync_base_env() -> None:
    """把托管监听地址写进客户端默认基址（未显式设 AKTOOLS_BASE 时）。"""
    if os.environ.get("AKTOOLS_BASE"):
        return
    os.environ["AKTOOLS_BASE"] = f"http://{listen_host()}:{listen_port()}"


def _spawn() -> subprocess.Popen:
    host = listen_host()
    port = listen_port()
    # 直接 uvicorn，避开 `python -m aktools` 再套一层 shell
    import aktools

    app_dir = os.path.dirname(os.path.abspath(aktools.__file__))
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        host,
        "--port",
        str(port),
        "--app-dir",
        app_dir,
    ]
    # Windows：独立进程组，便于整体结束；不继承控制台以免抢 Ctrl+C
    kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def ensure_started(*, wait_s: float = 20.0) -> dict[str, Any]:
    """确保 AKTools 可访问；必要时拉起子进程。"""
    global _PROC, _OWNED
    _sync_base_env()

    with _LOCK:
        if akc.available(timeout=1.0):
            return {
                "ok": True,
                "owned": _OWNED,
                "reused": True,
                "base": akc.base_url(),
                "version": akc.version(),
            }

        if not managed_enabled():
            return {
                "ok": False,
                "owned": False,
                "reused": False,
                "base": akc.base_url(),
                "error": "AKTools 未运行，且 AKTOOLS_MANAGED=0",
            }

        if _PROC is not None and _PROC.poll() is None:
            proc = _PROC
        else:
            try:
                import aktools  # noqa: F401
            except ImportError as exc:
                return {
                    "ok": False,
                    "owned": False,
                    "reused": False,
                    "base": akc.base_url(),
                    "error": f"未安装 aktools：{exc}",
                }
            try:
                proc = _spawn()
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "owned": False,
                    "reused": False,
                    "base": akc.base_url(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            _PROC = proc
            _OWNED = True

        deadline = time.time() + max(1.0, wait_s)
        while time.time() < deadline:
            if proc.poll() is not None:
                _PROC = None
                _OWNED = False
                return {
                    "ok": False,
                    "owned": False,
                    "reused": False,
                    "base": akc.base_url(),
                    "error": f"AKTools 子进程已退出，code={proc.returncode}",
                }
            if akc.available(timeout=0.8):
                return {
                    "ok": True,
                    "owned": True,
                    "reused": False,
                    "base": akc.base_url(),
                    "pid": proc.pid,
                    "version": akc.version(),
                }
            time.sleep(0.25)

        return {
            "ok": False,
            "owned": _OWNED,
            "reused": False,
            "base": akc.base_url(),
            "pid": proc.pid if proc.poll() is None else None,
            "error": f"等待 AKTools 就绪超时（{wait_s}s）",
        }


def stop_if_owned() -> None:
    """仅结束本模块拉起的子进程。"""
    global _PROC, _OWNED
    with _LOCK:
        if keep_alive() or not _OWNED or _PROC is None:
            return
        proc = _PROC
        _PROC = None
        _OWNED = False
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass


def runtime_status() -> dict[str, Any]:
    st = akc.status()
    st["managed_enabled"] = managed_enabled()
    st["owned"] = _OWNED
    st["pid"] = _PROC.pid if _PROC is not None and _PROC.poll() is None else None
    st["listen"] = f"{listen_host()}:{listen_port()}"
    return st
