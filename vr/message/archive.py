"""消息 raw 历史归档 —— 立即生效且超过保留期的消息移入独立库。"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .schemas import ListQuery, RawMessage
from .store import (
    BEIJING,
    DB_PATH,
    MSG_DIR,
    _LOCK,
    _connect,
    _row_raw,
    init_db,
)

ARCHIVE_DB_PATH = os.path.join(MSG_DIR, "messages_archive.db")
ARCHIVE_DAYS = int(os.environ.get("MSG_ARCHIVE_DAYS", "30"))


def archive_path_for_main(main_path: str | None) -> str:
    """与主库同目录的归档库路径（测试库与生产库分离）。"""
    if not main_path:
        return ARCHIVE_DB_PATH
    base, ext = os.path.splitext(main_path)
    return f"{base}_archive{ext or '.db'}"


def _connect_archive(path: Optional[str] = None) -> sqlite3.Connection:
    db = path or ARCHIVE_DB_PATH
    os.makedirs(os.path.dirname(db), exist_ok=True)
    conn = sqlite3.connect(db, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_archive_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS raw_message (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            source_label TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            url TEXT NOT NULL DEFAULT '',
            marks_json TEXT NOT NULL DEFAULT '[]',
            content_hash TEXT NOT NULL,
            batch_id TEXT,
            external_ref TEXT,
            produced_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}',
            withdrawn INTEGER NOT NULL DEFAULT 0,
            archived_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_source_ext
            ON raw_message(source_id, external_ref)
            WHERE external_ref IS NOT NULL AND external_ref != '';
        CREATE INDEX IF NOT EXISTS idx_archive_produced ON raw_message(produced_at);
        CREATE INDEX IF NOT EXISTS idx_archive_source ON raw_message(source_id);
        """
    )


def init_archive_db(path: Optional[str] = None) -> str:
    db = path or ARCHIVE_DB_PATH
    with _LOCK:
        with closing(_connect_archive(db)) as conn:
            _ensure_archive_schema(conn)
            conn.commit()
    return db


def _archive_cutoff(*, days: int | None = None) -> str:
    span = days if days is not None else ARCHIVE_DAYS
    dt = datetime.now(BEIJING) - timedelta(days=max(1, span))
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def archive_immediate_expired(
    *,
    days: int | None = None,
    main_path: str | None = None,
    archive_path: str | None = None,
) -> dict[str, Any]:
    """将生效方式为立即、产生时间早于保留期的消息 raw 移入归档库，并清理主库分析记录。"""
    init_db(main_path)
    arc_db = archive_path or archive_path_for_main(main_path)
    init_archive_db(arc_db)
    main_db = main_path or DB_PATH
    cutoff = _archive_cutoff(days=days)
    now = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    archived = 0
    deleted_analyzed = 0

    with _LOCK:
        with closing(_connect_archive(arc_db)) as arc_conn:
            with closing(_connect(main_db)) as main_conn:
                rows = main_conn.execute(
                    """
                    SELECT id FROM analyzed_message
                    WHERE effective_mode = 'immediate' AND produced_at < ?
                    """,
                    (cutoff,),
                ).fetchall()
                if not rows:
                    return {"archived": 0, "deleted_analyzed": 0, "cutoff": cutoff}

                analyzed_ids = [r["id"] for r in rows]
                placeholders = ",".join("?" * len(analyzed_ids))
                raw_rows = main_conn.execute(
                    f"""
                    SELECT r.* FROM raw_message r
                    INNER JOIN raw_analyzed_link l ON l.raw_id = r.id
                    WHERE l.analyzed_id IN ({placeholders})
                    """,
                    analyzed_ids,
                ).fetchall()

                for r in raw_rows:
                    arc_conn.execute(
                        """
                        INSERT OR IGNORE INTO raw_message (
                            id, source_id, source_label, content, title, keywords_json, url, marks_json,
                            content_hash, batch_id, external_ref, produced_at, ingested_at, meta_json,
                            withdrawn, archived_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            r["id"],
                            r["source_id"],
                            r["source_label"],
                            r["content"],
                            r["title"],
                            r["keywords_json"],
                            r["url"],
                            r["marks_json"],
                            r["content_hash"],
                            r["batch_id"],
                            r["external_ref"],
                            r["produced_at"],
                            r["ingested_at"],
                            r["meta_json"],
                            r["withdrawn"],
                            now,
                        ),
                    )
                    if arc_conn.total_changes:
                        archived += 1

                main_conn.execute(
                    f"DELETE FROM impact_target WHERE analyzed_id IN ({placeholders})",
                    analyzed_ids,
                )
                main_conn.execute(
                    f"DELETE FROM raw_analyzed_link WHERE analyzed_id IN ({placeholders})",
                    analyzed_ids,
                )
                cur = main_conn.execute(
                    f"DELETE FROM analyzed_message WHERE id IN ({placeholders})",
                    analyzed_ids,
                )
                deleted_analyzed = int(cur.rowcount)

                raw_ids = [r["id"] for r in raw_rows]
                if raw_ids:
                    rp = ",".join("?" * len(raw_ids))
                    main_conn.execute(f"DELETE FROM raw_message WHERE id IN ({rp})", raw_ids)

                arc_conn.commit()
                main_conn.commit()

    return {"archived": archived, "deleted_analyzed": deleted_analyzed, "cutoff": cutoff}


def _build_archive_where(q: ListQuery) -> tuple[str, list[Any]]:
    parts = ["1=1"]
    args: list[Any] = []
    if q.source:
        srcs = [s.strip() for s in q.source.split(",") if s.strip()]
        if len(srcs) == 1:
            parts.append("source_id = ?")
            args.append(srcs[0])
        elif srcs:
            parts.append(f"source_id IN ({','.join('?' * len(srcs))})")
            args.extend(srcs)
    if q.from_dt:
        parts.append("produced_at >= ?")
        args.append(q.from_dt)
    if q.to_dt:
        parts.append("produced_at <= ?")
        args.append(q.to_dt)
    if q.q:
        like = f"%{q.q.strip()}%"
        parts.append(
            "(title LIKE ? OR content LIKE ? OR keywords_json LIKE ? OR source_label LIKE ?)"
        )
        args.extend([like, like, like, like])
    return " AND ".join(parts), args


def list_raw_archive(
    q: ListQuery,
    *,
    path: Optional[str] = None,
) -> tuple[list[RawMessage], int]:
    init_archive_db(path)
    db = path or ARCHIVE_DB_PATH
    where, args = _build_archive_where(q)
    sort_col = q.sort if q.sort in ("produced_at", "ingested_at", "title") else "produced_at"
    order = "ASC" if q.order == "asc" else "DESC"
    limit = max(1, min(q.limit, 200))
    offset = max(0, q.offset)
    with _LOCK:
        with closing(_connect_archive(db)) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM raw_message WHERE {where}", args
            ).fetchone()["c"]
            rows = conn.execute(
                f"""
                SELECT id, source_id, source_label, content, title, keywords_json, url, marks_json,
                       content_hash, batch_id, external_ref, produced_at, ingested_at, meta_json
                FROM raw_message WHERE {where}
                ORDER BY {sort_col} {order} LIMIT ? OFFSET ?
                """,
                [*args, limit, offset],
            ).fetchall()
    return [_row_raw(r) for r in rows], int(total)


def get_raw_archive(raw_id: str, *, path: Optional[str] = None) -> RawMessage | None:
    init_archive_db(path)
    db = path or ARCHIVE_DB_PATH
    with _LOCK:
        with closing(_connect_archive(db)) as conn:
            r = conn.execute(
                """
                SELECT id, source_id, source_label, content, title, keywords_json, url, marks_json,
                       content_hash, batch_id, external_ref, produced_at, ingested_at, meta_json
                FROM raw_message WHERE id = ?
                """,
                (raw_id,),
            ).fetchone()
    return _row_raw(r) if r else None


def external_ref_in_archive(
    source_id: str,
    external_ref: str,
    *,
    path: Optional[str] = None,
    archive_path: Optional[str] = None,
) -> bool:
    if not external_ref:
        return False
    arc_db = archive_path or archive_path_for_main(path)
    init_archive_db(arc_db)
    with _LOCK:
        with closing(_connect_archive(arc_db)) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM raw_message
                WHERE source_id = ? AND external_ref = ? AND withdrawn = 0
                LIMIT 1
                """,
                (source_id, external_ref),
            ).fetchone()
    return row is not None
