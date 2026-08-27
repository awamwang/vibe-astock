"""插件上报的当前股票 —— 进程内存储，供 API 与同花顺板块等模块读取。"""

from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import china_now

_STATE_DIR = Path.home() / ".vibe-astock"
_LEGACY_STATE_FILE = _STATE_DIR / "ths-linker-current.json"

_lock = threading.Lock()
_current: CurrentStock | None = None
_listeners: list[queue.Queue[dict[str, Any] | None]] = []


@dataclass(frozen=True)
class CurrentStock:
    code: str
    plugin_id: str
    source: str
    prev: str | None
    updated_at: str
    ths_dir: str | None = None
    symbol: str | None = None
    market_id: str | None = None
    instance_id: str | None = None


def _normalize_code(raw: Any) -> str:
    code = str(raw or "").strip()
    if len(code) != 6 or not code.isdigit():
        raise ValueError("股票代码须为 6 位数字")
    return code


def _now_str() -> str:
    return china_now().strftime("%Y-%m-%d %H:%M:%S")


def report(plugin_id: str, payload: dict) -> CurrentStock | None:
    """插件上报当前股票；代码未变时返回 None。"""
    global _current
    body = dict(payload or {})
    code = _normalize_code(body.get("code"))
    with _lock:
        if _current is not None and _current.code == code:
            return None
        prev_raw = body.get("prev")
        if prev_raw is not None and str(prev_raw).strip():
            prev: str | None = str(prev_raw).strip()
        elif _current is not None:
            prev = _current.code
        else:
            prev = None
        inst = body.get("instance_id")
        rec = CurrentStock(
            code=code,
            plugin_id=str(plugin_id or ""),
            source=str(body.get("source") or "plugin"),
            prev=prev,
            updated_at=_now_str(),
            ths_dir=str(body.get("ths_dir") or "").strip() or None,
            symbol=str(body.get("symbol") or "").strip() or None,
            market_id=str(body.get("market_id") or "").strip() or None,
            instance_id=str(inst).strip() if inst is not None and str(inst).strip() else None,
        )
        _current = rec
    _persist_legacy(rec)
    _notify_listeners(to_dict(rec))
    return rec


def subscribe() -> queue.Queue[dict[str, Any] | None]:
    """订阅当前股票变化；连接后立即收到一次快照（若有）。"""
    q: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=8)
    with _lock:
        _listeners.append(q)
        snap = to_dict(_current)
    if snap:
        try:
            q.put_nowait(snap)
        except queue.Full:
            pass
    return q


def unsubscribe(q: queue.Queue[dict[str, Any] | None]) -> None:
    with _lock:
        if q in _listeners:
            _listeners.remove(q)


def _notify_listeners(data: dict[str, Any]) -> None:
    with _lock:
        listeners = list(_listeners)
    for q in listeners:
        try:
            q.put_nowait(data)
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(data)
            except queue.Full:
                pass


def get_current() -> CurrentStock | None:
    with _lock:
        return _current


def to_dict(st: CurrentStock | None = None) -> dict[str, Any] | None:
    rec = st if st is not None else get_current()
    if rec is None:
        return None
    out: dict[str, Any] = {
        "code": rec.code,
        "plugin_id": rec.plugin_id,
        "source": rec.source,
        "prev": rec.prev,
        "updated_at": rec.updated_at,
    }
    if rec.ths_dir:
        out["ths_dir"] = rec.ths_dir
    if rec.symbol:
        out["symbol"] = rec.symbol
    if rec.market_id:
        out["market_id"] = rec.market_id
    if rec.instance_id:
        out["instance_id"] = rec.instance_id
    return out


def _persist_legacy(rec: CurrentStock) -> None:
    """兼容读取 ~/.vibe-astock/ths-linker-current.json 的模块。"""
    if not rec.ths_dir:
        return
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _LEGACY_STATE_FILE.write_text(
            json.dumps(to_dict(rec), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def load_legacy_ths_dir() -> str | None:
    """从内存状态或遗留状态文件解析同花顺安装目录。"""
    rec = get_current()
    if rec and rec.ths_dir:
        return rec.ths_dir
    if not _LEGACY_STATE_FILE.is_file():
        return None
    try:
        data = json.loads(_LEGACY_STATE_FILE.read_text(encoding="utf-8"))
        ths_dir = str(data.get("ths_dir") or "").strip()
        return ths_dir or None
    except (OSError, json.JSONDecodeError, TypeError):
        return None
