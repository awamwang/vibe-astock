"""长序列 SQLite 落盘。

路径与其它本机数据一致：`~/.duanxian-agents/cache/series.db`。
按日定稿的 JSON 缓存不迁入；仅两融 / 指数 / 成交额 / 情绪分位等会增长、反复合并的序列。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from typing import Any, Optional

from . import paths as _paths
from .util import china_now

DATA_ROOT = ""
_CACHE_DIR = ""
DB_PATH = ""


@_paths.register_rebind
def _rebind_paths() -> None:
    global DATA_ROOT, _CACHE_DIR, DB_PATH
    DATA_ROOT = str(_paths.agents_dir())
    _CACHE_DIR = os.path.join(DATA_ROOT, "cache")
    DB_PATH = os.path.join(_CACHE_DIR, "series.db")

SERIES_MARGIN = "margin_sse"
SERIES_INDEX = "sh000001"
SERIES_AMOUNT = "market_amount"
SERIES_SENTIMENT = "sentiment_s"

_SCHEMA = 1
_LOCK = threading.Lock()
_INITED = False


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    db = path or DB_PATH
    os.makedirs(os.path.dirname(db), exist_ok=True)
    conn = sqlite3.connect(db, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS series_meta (
            name TEXT PRIMARY KEY,
            schema INTEGER NOT NULL,
            updated_at TEXT,
            source TEXT
        );
        CREATE TABLE IF NOT EXISTS series_row (
            series TEXT NOT NULL,
            date TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (series, date)
        );
        CREATE INDEX IF NOT EXISTS idx_series_row_series
            ON series_row(series, date);
        """
    )


def init_db(path: Optional[str] = None) -> str:
    """确保库文件与表结构存在，返回 db 路径。"""
    global _INITED
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            _ensure_schema(conn)
            conn.commit()
        if path is None:
            _INITED = True
    return db


def _now() -> str:
    return china_now().strftime("%Y-%m-%d %H:%M:%S")


def load_envelope(series: str, *, path: Optional[str] = None) -> dict[str, Any]:
    """读某序列：`{schema, rows, updated_at, source}`，按 date 升序。"""
    init_db(path)
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            meta = conn.execute(
                "SELECT schema, updated_at, source FROM series_meta WHERE name = ?",
                (series,),
            ).fetchone()
            rows_raw = conn.execute(
                "SELECT date, payload FROM series_row WHERE series = ? ORDER BY date",
                (series,),
            ).fetchall()
    rows: list[dict] = []
    for r in rows_raw:
        try:
            payload = json.loads(r["payload"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        item = dict(payload)
        item["date"] = r["date"]
        rows.append(item)
    return {
        "schema": int(meta["schema"]) if meta else _SCHEMA,
        "rows": rows,
        "updated_at": meta["updated_at"] if meta else None,
        "source": meta["source"] if meta else None,
    }


def replace_rows(
    series: str,
    rows: list[dict],
    *,
    source: Optional[str] = None,
    path: Optional[str] = None,
) -> dict[str, Any]:
    """整序列替换写入（增量合并由调用方完成后再调用）。"""
    init_db(path)
    db = path or DB_PATH
    updated_at = _now()
    with _LOCK:
        with closing(_connect(db)) as conn:
            conn.execute("DELETE FROM series_row WHERE series = ?", (series,))
            for row in rows:
                d = row.get("date")
                if not d:
                    continue
                payload = {k: v for k, v in row.items() if k != "date"}
                conn.execute(
                    "INSERT INTO series_row(series, date, payload) VALUES (?, ?, ?)",
                    (series, str(d), json.dumps(payload, ensure_ascii=False)),
                )
            conn.execute(
                """
                INSERT INTO series_meta(name, schema, updated_at, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    schema = excluded.schema,
                    updated_at = excluded.updated_at,
                    source = COALESCE(excluded.source, series_meta.source)
                """,
                (series, _SCHEMA, updated_at, source),
            )
            conn.commit()
    return {
        "schema": _SCHEMA,
        "rows": rows,
        "updated_at": updated_at,
        "source": source,
    }


def row_count(series: str, *, path: Optional[str] = None) -> int:
    init_db(path)
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM series_row WHERE series = ?",
                (series,),
            ).fetchone()
    return int(n["n"]) if n else 0


def migrate_json_file(
    series: str,
    json_path: str,
    *,
    path: Optional[str] = None,
) -> bool:
    """库内该序列为空且旧 JSON 存在时，导入一次。成功返回 True。"""
    if row_count(series, path=path) > 0:
        return False
    if not os.path.isfile(json_path):
        return False
    try:
        with open(json_path, encoding="utf-8") as fh:
            env = json.load(fh)
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(env, dict) or not isinstance(env.get("rows"), list):
        return False
    rows = [r for r in env["rows"] if isinstance(r, dict) and r.get("date")]
    if not rows:
        return False
    replace_rows(
        series,
        rows,
        source=str(env.get("source") or "json_migrate"),
        path=path,
    )
    # 保留旧 JSON 作备份，不删除
    return True


def list_series(*, path: Optional[str] = None) -> list[dict[str, Any]]:
    """各序列摘要，供数据管理页展示。"""
    init_db(path)
    db = path or DB_PATH
    known = (
        SERIES_MARGIN,
        SERIES_INDEX,
        SERIES_AMOUNT,
        SERIES_SENTIMENT,
    )
    with _LOCK:
        with closing(_connect(db)) as conn:
            out: list[dict[str, Any]] = []
            for name in known:
                meta = conn.execute(
                    "SELECT updated_at, source FROM series_meta WHERE name = ?",
                    (name,),
                ).fetchone()
                bounds = conn.execute(
                    """
                    SELECT COUNT(*) AS n,
                           MIN(date) AS first,
                           MAX(date) AS last
                    FROM series_row WHERE series = ?
                    """,
                    (name,),
                ).fetchone()
                out.append({
                    "name": name,
                    "days": int(bounds["n"] or 0),
                    "first": bounds["first"],
                    "last": bounds["last"],
                    "updated_at": meta["updated_at"] if meta else None,
                    "source": meta["source"] if meta else None,
                })
    return out


def overview(*, path: Optional[str] = None) -> dict[str, Any]:
    db = path or DB_PATH
    init_db(path)
    size = 0
    if os.path.isfile(db):
        try:
            size = os.path.getsize(db)
        except OSError:
            size = 0
    series = list_series(path=path)
    return {
        "db_path": db,
        "byte_count": size,
        "series": series,
        "total_days": sum(int(s.get("days") or 0) for s in series),
    }


def export_json_bundle(
    dest_dir: str,
    *,
    path: Optional[str] = None,
    root_label: str = "series",
) -> dict[str, Any]:
    """把长序列导出为可读 JSON 目录（不依赖 SQLite 工具）。

    写出 `dest_dir/<archive_name>/` 下各序列 `.json`，并返回路径与统计。
    """
    from pathlib import Path

    text = (dest_dir or "").strip().strip('"').strip("'")
    if not text:
        raise ValueError("请填写导出目录")
    dest = Path(text).expanduser()
    if not dest.is_absolute():
        dest = _paths.profile_root() / dest
    dest = dest.resolve()
    if dest.exists() and not dest.is_dir():
        raise ValueError(f"导出路径不是目录：{dest}")
    dest.mkdir(parents=True, exist_ok=True)

    stamp = china_now().strftime("%Y%m%d-%H%M%S")
    out_dir = dest / f"duanxian-series-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=False)

    files: list[str] = []
    total_rows = 0
    for item in list_series(path=path):
        name = item["name"]
        env = load_envelope(name, path=path)
        payload = {
            "schema": env.get("schema"),
            "series": name,
            "updated_at": env.get("updated_at"),
            "source": env.get("source"),
            "rows": env.get("rows") or [],
        }
        fp = out_dir / f"{name}.json"
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        files.append(fp.name)
        total_rows += len(payload["rows"])

    meta = {
        "format": "vibe-astock-series-json",
        "version": 1,
        "created_at": _now() + " CST",
        "db_path": path or DB_PATH,
        "files": files,
        "row_count": total_rows,
        "root_label": root_label,
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    return {
        "ok": True,
        "path": str(out_dir),
        "file_count": len(files) + 1,
        "row_count": total_rows,
        "files": files,
        "db_path": path or DB_PATH,
    }
