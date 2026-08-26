"""消息分析 SQLite 落盘 —— ~/.duanxian-agents/messages/messages.db"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from .schemas import (
    AnalyzedMessage,
    ImpactTarget,
    ListQuery,
    MessageSourceInfo,
    RawMessage,
    RawMessageDraft,
)

DATA_ROOT = os.path.expanduser("~/.duanxian-agents")
MSG_DIR = os.path.join(DATA_ROOT, "messages")
DB_PATH = os.path.join(MSG_DIR, "messages.db")
BEIJING = timezone(timedelta(hours=8))
_LOCK = threading.Lock()
_INITED = False

DEFAULT_SOURCES = [
    ("paste", "粘贴录入", "manual", 1, None),
    ("structured", "结构化 JSON", "manual", 1, None),
    ("calendar", "财经大事日历", "manual", 1, None),
    ("xgb_msgs", "选股宝快讯", "poll", 1, 30),
]


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    db = path or DB_PATH
    os.makedirs(os.path.dirname(db), exist_ok=True)
    conn = sqlite3.connect(db, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _json_loads(s: str | None, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (TypeError, json.JSONDecodeError):
        return default


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def new_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS message_source (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            adapter_type TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            poll_interval_s INTEGER,
            config_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS poll_state (
            source_id TEXT PRIMARY KEY,
            head_mark TEXT,
            tail_mark TEXT,
            last_poll_at TEXT,
            last_error TEXT
        );
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
            withdrawn INTEGER NOT NULL DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_source_ext
            ON raw_message(source_id, external_ref)
            WHERE external_ref IS NOT NULL AND external_ref != '';
        CREATE INDEX IF NOT EXISTS idx_raw_produced ON raw_message(produced_at);
        CREATE INDEX IF NOT EXISTS idx_raw_source ON raw_message(source_id);
        CREATE INDEX IF NOT EXISTS idx_raw_hash ON raw_message(content_hash);
        CREATE TABLE IF NOT EXISTS analyzed_message (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            source_label TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            url TEXT NOT NULL DEFAULT '',
            marks_json TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            effective_mode TEXT NOT NULL DEFAULT 'immediate',
            effective_at TEXT,
            produced_at TEXT NOT NULL,
            impact_level TEXT NOT NULL DEFAULT 'medium',
            freshness TEXT NOT NULL DEFAULT 'new',
            effect_status TEXT NOT NULL DEFAULT 'not_erupted',
            analyzed_at TEXT,
            analyzed_by TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'draft'
        );
        CREATE INDEX IF NOT EXISTS idx_analyzed_produced ON analyzed_message(produced_at);
        CREATE INDEX IF NOT EXISTS idx_analyzed_level ON analyzed_message(impact_level);
        CREATE INDEX IF NOT EXISTS idx_analyzed_effect ON analyzed_message(effect_status);
        CREATE TABLE IF NOT EXISTS raw_analyzed_link (
            raw_id TEXT NOT NULL,
            analyzed_id TEXT NOT NULL,
            PRIMARY KEY (raw_id, analyzed_id)
        );
        CREATE TABLE IF NOT EXISTS impact_target (
            analyzed_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            code TEXT,
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_target_analyzed ON impact_target(analyzed_id);
        CREATE TABLE IF NOT EXISTS analyze_job (
            id TEXT PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error TEXT
        );
        """
    )
    for sid, label, atype, enabled, interval in DEFAULT_SOURCES:
        conn.execute(
            """
            INSERT OR IGNORE INTO message_source (id, label, adapter_type, enabled, poll_interval_s)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sid, label, atype, enabled, interval),
        )


def init_db(path: Optional[str] = None) -> str:
    global _INITED
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            _ensure_schema(conn)
            conn.commit()
        if path is None:
            _INITED = True
    return db


def _row_raw(r: sqlite3.Row) -> RawMessage:
    return RawMessage(
        id=r["id"],
        source_id=r["source_id"],
        source_label=r["source_label"] or "",
        content=r["content"] or "",
        title=r["title"] or "",
        keywords=_json_loads(r["keywords_json"], []),
        url=r["url"] or "",
        marks=_json_loads(r["marks_json"], []),
        content_hash=r["content_hash"] or "",
        batch_id=r["batch_id"],
        external_ref=r["external_ref"],
        produced_at=r["produced_at"],
        ingested_at=r["ingested_at"],
        meta=_json_loads(r["meta_json"], {}),
    )


def _row_analyzed(r: sqlite3.Row, targets: list[ImpactTarget], raw_ids: list[str]) -> AnalyzedMessage:
    return AnalyzedMessage(
        id=r["id"],
        raw_ids=raw_ids,
        source_id=r["source_id"],
        source_label=r["source_label"] or "",
        title=r["title"] or "",
        keywords=_json_loads(r["keywords_json"], []),
        url=r["url"] or "",
        marks=_json_loads(r["marks_json"], []),
        summary=r["summary"] or "",
        detail=r["detail"] or "",
        effective_mode=r["effective_mode"] or "immediate",
        effective_at=r["effective_at"],
        produced_at=r["produced_at"],
        targets=targets,
        impact_level=r["impact_level"] or "medium",
        freshness=r["freshness"] or "new",
        effect_status=r["effect_status"] or "not_erupted",
        analyzed_at=r["analyzed_at"],
        analyzed_by=r["analyzed_by"],
        version=int(r["version"] or 1),
        status=r["status"] or "draft",
    )


def _load_targets(conn: sqlite3.Connection, analyzed_id: str) -> list[ImpactTarget]:
    rows = conn.execute(
        "SELECT kind, code, name FROM impact_target WHERE analyzed_id = ? ORDER BY sort_order",
        (analyzed_id,),
    ).fetchall()
    return [ImpactTarget(kind=r["kind"], code=r["code"], name=r["name"]) for r in rows]


def _load_raw_ids(conn: sqlite3.Connection, analyzed_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT raw_id FROM raw_analyzed_link WHERE analyzed_id = ?",
        (analyzed_id,),
    ).fetchall()
    return [r["raw_id"] for r in rows]


def list_sources(*, path: Optional[str] = None) -> list[MessageSourceInfo]:
    init_db(path)
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            rows = conn.execute(
                "SELECT id, label, adapter_type, enabled, poll_interval_s FROM message_source ORDER BY id"
            ).fetchall()
            out: list[MessageSourceInfo] = []
            for r in rows:
                ps = conn.execute(
                    "SELECT last_poll_at, last_error FROM poll_state WHERE source_id = ?",
                    (r["id"],),
                ).fetchone()
                out.append(
                    MessageSourceInfo(
                        id=r["id"],
                        label=r["label"],
                        adapter_type=r["adapter_type"],
                        enabled=bool(r["enabled"]),
                        poll_interval_s=r["poll_interval_s"],
                        last_poll_at=ps["last_poll_at"] if ps else None,
                        last_error=ps["last_error"] if ps else None,
                    )
                )
    return out


def get_poll_state(source_id: str, *, path: Optional[str] = None) -> dict[str, str | None]:
    init_db(path)
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            r = conn.execute(
                "SELECT head_mark, tail_mark, last_poll_at, last_error FROM poll_state WHERE source_id = ?",
                (source_id,),
            ).fetchone()
    if not r:
        return {"head_mark": None, "tail_mark": None, "last_poll_at": None, "last_error": None}
    return dict(r)


def set_poll_state(
    source_id: str,
    *,
    head_mark: str | None = None,
    tail_mark: str | None = None,
    last_error: str | None = None,
    path: Optional[str] = None,
) -> None:
    init_db(path)
    db = path or DB_PATH
    now = _now()
    with _LOCK:
        with closing(_connect(db)) as conn:
            conn.execute(
                """
                INSERT INTO poll_state (source_id, head_mark, tail_mark, last_poll_at, last_error)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    head_mark = COALESCE(excluded.head_mark, poll_state.head_mark),
                    tail_mark = COALESCE(excluded.tail_mark, poll_state.tail_mark),
                    last_poll_at = excluded.last_poll_at,
                    last_error = excluded.last_error
                """,
                (source_id, head_mark, tail_mark, now, last_error),
            )
            conn.commit()


def _draft_meta(d: RawMessageDraft) -> dict[str, Any]:
    meta = dict(d.meta or {})
    if d.targets:
        meta["_targets_json"] = [t.model_dump() for t in d.targets]
    return meta


def insert_raw_batch(
    drafts: list[RawMessageDraft],
    *,
    batch_id: str | None = None,
    path: Optional[str] = None,
) -> list[RawMessage]:
    if not drafts:
        return []
    init_db(path)
    db = path or DB_PATH
    bid = batch_id or new_id("batch")
    now = _now()
    inserted: list[RawMessage] = []
    with _LOCK:
        with closing(_connect(db)) as conn:
            for d in drafts:
                ext = d.external_ref
                body = d.content.strip()
                ch = content_hash(body or d.title)
                produced = d.produced_at or now
                meta = _draft_meta(d)

                if ext:
                    exists = conn.execute(
                        "SELECT id FROM raw_message WHERE source_id = ? AND external_ref = ? AND withdrawn = 0",
                        (d.source_id, ext),
                    ).fetchone()
                    if exists:
                        rid = exists["id"]
                        conn.execute(
                            """
                            UPDATE raw_message SET
                                content = ?, title = ?, keywords_json = ?, url = ?, marks_json = ?,
                                content_hash = ?, produced_at = ?, meta_json = ?
                            WHERE id = ?
                            """,
                            (
                                body,
                                d.title or "",
                                _json_dumps(d.keywords),
                                d.url or "",
                                _json_dumps(d.marks),
                                ch,
                                produced,
                                _json_dumps(meta),
                                rid,
                            ),
                        )
                        row = conn.execute("SELECT * FROM raw_message WHERE id = ?", (rid,)).fetchone()
                        if row:
                            inserted.append(_row_raw(row))
                        continue

                dup = conn.execute(
                    "SELECT id FROM raw_message WHERE source_id = ? AND content_hash = ? AND withdrawn = 0",
                    (d.source_id, ch),
                ).fetchone()
                if dup and not ext:
                    continue
                rid = f"xgb_{ext}" if ext and d.source_id == "xgb_msgs" else new_id()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO raw_message (
                        id, source_id, source_label, content, title, keywords_json, url, marks_json,
                        content_hash, batch_id, external_ref, produced_at, ingested_at, meta_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rid,
                        d.source_id,
                        d.source_label,
                        body,
                        d.title or "",
                        _json_dumps(d.keywords),
                        d.url or "",
                        _json_dumps(d.marks),
                        ch,
                        bid,
                        ext,
                        produced,
                        now,
                        _json_dumps(meta),
                    ),
                )
                if conn.total_changes:
                    inserted.append(
                        RawMessage(
                            id=rid,
                            source_id=d.source_id,
                            source_label=d.source_label,
                            content=body,
                            title=d.title or "",
                            keywords=list(d.keywords),
                            url=d.url or "",
                            marks=list(d.marks),
                            content_hash=ch,
                            batch_id=bid,
                            external_ref=ext,
                            produced_at=produced,
                            ingested_at=now,
                            meta=meta,
                        )
                    )
            conn.commit()
    return inserted


def _sync_impact_targets(
    conn: sqlite3.Connection,
    analyzed_id: str,
    targets: list[Any],
) -> None:
    conn.execute("DELETE FROM impact_target WHERE analyzed_id = ?", (analyzed_id,))
    if not isinstance(targets, list):
        return
    for i, t in enumerate(targets):
        if isinstance(t, dict):
            conn.execute(
                """
                INSERT INTO impact_target (analyzed_id, kind, code, name, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    analyzed_id,
                    t.get("kind", "other"),
                    t.get("code"),
                    t.get("name", ""),
                    i,
                ),
            )


def _resolve_targets(raw: RawMessage, patch: dict[str, Any]) -> list[Any]:
    if "targets" in patch and patch["targets"] is not None:
        return patch["targets"]
    from_meta = _json_loads(raw.meta.get("_targets_json"), [])
    if from_meta:
        return from_meta
    return []


def mark_withdrawn(source_id: str, external_ref: str, *, path: Optional[str] = None) -> bool:
    init_db(path)
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            cur = conn.execute(
                """
                UPDATE raw_message SET withdrawn = 1
                WHERE source_id = ? AND external_ref = ?
                """,
                (source_id, external_ref),
            )
            conn.commit()
            return cur.rowcount > 0


def _build_raw_where(q: ListQuery) -> tuple[str, list[Any]]:
    parts = ["withdrawn = 0"]
    args: list[Any] = []
    if q.source:
        parts.append("source_id = ?")
        args.append(q.source)
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


def list_raw(q: ListQuery, *, path: Optional[str] = None) -> tuple[list[RawMessage], int]:
    init_db(path)
    db = path or DB_PATH
    where, args = _build_raw_where(q)
    sort_col = q.sort if q.sort in ("produced_at", "ingested_at", "title") else "produced_at"
    order = "ASC" if q.order == "asc" else "DESC"
    limit = max(1, min(q.limit, 200))
    offset = max(0, q.offset)
    with _LOCK:
        with closing(_connect(db)) as conn:
            total = conn.execute(f"SELECT COUNT(*) AS c FROM raw_message WHERE {where}", args).fetchone()["c"]
            rows = conn.execute(
                f"""
                SELECT * FROM raw_message WHERE {where}
                ORDER BY {sort_col} {order} LIMIT ? OFFSET ?
                """,
                [*args, limit, offset],
            ).fetchall()
    return [_row_raw(r) for r in rows], int(total)


def get_raw(raw_id: str, *, path: Optional[str] = None) -> RawMessage | None:
    init_db(path)
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            r = conn.execute("SELECT * FROM raw_message WHERE id = ?", (raw_id,)).fetchone()
    return _row_raw(r) if r else None


def get_analyzed_for_raw(raw_id: str, *, path: Optional[str] = None) -> AnalyzedMessage | None:
    init_db(path)
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            link = conn.execute(
                "SELECT analyzed_id FROM raw_analyzed_link WHERE raw_id = ? LIMIT 1",
                (raw_id,),
            ).fetchone()
            if not link:
                return None
            r = conn.execute(
                "SELECT * FROM analyzed_message WHERE id = ?",
                (link["analyzed_id"],),
            ).fetchone()
            if not r:
                return None
            aid = r["id"]
            return _row_analyzed(r, _load_targets(conn, aid), _load_raw_ids(conn, aid))


def _build_analyzed_where(q: ListQuery) -> tuple[str, list[Any]]:
    parts = ["1=1"]
    args: list[Any] = []
    if q.source:
        parts.append("source_id = ?")
        args.append(q.source)
    if q.from_dt:
        parts.append("produced_at >= ?")
        args.append(q.from_dt)
    if q.to_dt:
        parts.append("produced_at <= ?")
        args.append(q.to_dt)
    if q.impact_level:
        parts.append("impact_level = ?")
        args.append(q.impact_level)
    if q.effect_status:
        parts.append("effect_status = ?")
        args.append(q.effect_status)
    if q.status:
        parts.append("status = ?")
        args.append(q.status)
    if q.q:
        like = f"%{q.q.strip()}%"
        parts.append(
            "(title LIKE ? OR summary LIKE ? OR detail LIKE ? OR keywords_json LIKE ?)"
        )
        args.extend([like, like, like, like])
    return " AND ".join(parts), args


def list_analyzed(q: ListQuery, *, path: Optional[str] = None) -> tuple[list[AnalyzedMessage], int]:
    init_db(path)
    db = path or DB_PATH
    where, args = _build_analyzed_where(q)
    sort_map = {
        "produced_at": "produced_at",
        "ingested_at": "analyzed_at",
        "impact_level": "impact_level",
        "title": "title",
    }
    sort_col = sort_map.get(q.sort, "produced_at")
    order = "ASC" if q.order == "asc" else "DESC"
    limit = max(1, min(q.limit, 200))
    offset = max(0, q.offset)
    with _LOCK:
        with closing(_connect(db)) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM analyzed_message WHERE {where}", args
            ).fetchone()["c"]
            rows = conn.execute(
                f"""
                SELECT * FROM analyzed_message WHERE {where}
                ORDER BY {sort_col} {order} LIMIT ? OFFSET ?
                """,
                [*args, limit, offset],
            ).fetchall()
            out: list[AnalyzedMessage] = []
            for r in rows:
                aids = r["id"]
                targets = _load_targets(conn, aids)
                raw_ids = _load_raw_ids(conn, aids)
                out.append(_row_analyzed(r, targets, raw_ids))
    return out, int(total)


def get_analyzed(analyzed_id: str, *, path: Optional[str] = None) -> AnalyzedMessage | None:
    init_db(path)
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            r = conn.execute("SELECT * FROM analyzed_message WHERE id = ?", (analyzed_id,)).fetchone()
            if not r:
                return None
            return _row_analyzed(r, _load_targets(conn, analyzed_id), _load_raw_ids(conn, analyzed_id))


def upsert_analyzed_from_raw(
    raw: RawMessage,
    *,
    patch: dict[str, Any] | None = None,
    analyzed_by: str = "rule",
    path: Optional[str] = None,
) -> AnalyzedMessage:
    """从原始消息生成或更新 draft 分析记录。"""
    init_db(path)
    db = path or DB_PATH
    now = _now()
    patch = patch or {}
    with _LOCK:
        with closing(_connect(db)) as conn:
            link = conn.execute(
                "SELECT analyzed_id FROM raw_analyzed_link WHERE raw_id = ? LIMIT 1",
                (raw.id,),
            ).fetchone()
            if link:
                aid = link["analyzed_id"]
                conn.execute(
                    """
                    UPDATE analyzed_message SET
                        title = COALESCE(?, title),
                        keywords_json = COALESCE(?, keywords_json),
                        url = COALESCE(?, url),
                        marks_json = COALESCE(?, marks_json),
                        summary = COALESCE(?, summary),
                        detail = COALESCE(?, detail),
                        version = version + 1,
                        analyzed_at = ?,
                        analyzed_by = ?
                    WHERE id = ?
                    """,
                    (
                        patch.get("title"),
                        _json_dumps(patch["keywords"]) if "keywords" in patch else None,
                        patch.get("url"),
                        _json_dumps(patch["marks"]) if "marks" in patch else None,
                        patch.get("summary"),
                        patch.get("detail"),
                        now,
                        analyzed_by,
                        aid,
                    ),
                )
                _sync_impact_targets(conn, aid, _resolve_targets(raw, patch))
            else:
                aid = new_id("an")
                summary = patch.get("summary") or (raw.title[:120] if raw.title else raw.content[:120])
                conn.execute(
                    """
                    INSERT INTO analyzed_message (
                        id, source_id, source_label, title, keywords_json, url, marks_json,
                        summary, detail, effective_mode, effective_at, produced_at,
                        impact_level, freshness, effect_status, analyzed_at, analyzed_by, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        aid,
                        raw.source_id,
                        raw.source_label,
                        patch.get("title", raw.title),
                        _json_dumps(patch.get("keywords", raw.keywords)),
                        patch.get("url", raw.url),
                        _json_dumps(patch.get("marks", raw.marks)),
                        summary,
                        patch.get("detail", raw.content),
                        patch.get("effective_mode", "immediate"),
                        patch.get("effective_at"),
                        raw.produced_at,
                        patch.get("impact_level", "medium"),
                        patch.get("freshness", "new"),
                        patch.get("effect_status", "not_erupted"),
                        now,
                        analyzed_by,
                        patch.get("status", "draft"),
                    ),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO raw_analyzed_link (raw_id, analyzed_id) VALUES (?, ?)",
                    (raw.id, aid),
                )
                _sync_impact_targets(conn, aid, _resolve_targets(raw, patch))
            conn.commit()
    result = get_analyzed(aid, path=path)
    assert result is not None
    return result


def update_analyzed(analyzed_id: str, patch: dict[str, Any], *, path: Optional[str] = None) -> AnalyzedMessage | None:
    init_db(path)
    db = path or DB_PATH
    now = _now()
    with _LOCK:
        with closing(_connect(db)) as conn:
            r = conn.execute("SELECT id FROM analyzed_message WHERE id = ?", (analyzed_id,)).fetchone()
            if not r:
                return None
            fields: list[str] = []
            args: list[Any] = []
            scalar_map = {
                "title": "title",
                "url": "url",
                "summary": "summary",
                "detail": "detail",
                "effective_mode": "effective_mode",
                "effective_at": "effective_at",
                "produced_at": "produced_at",
                "impact_level": "impact_level",
                "freshness": "freshness",
                "effect_status": "effect_status",
                "status": "status",
                "source_label": "source_label",
            }
            for k, col in scalar_map.items():
                if k in patch:
                    fields.append(f"{col} = ?")
                    args.append(patch[k])
            if "keywords" in patch:
                fields.append("keywords_json = ?")
                args.append(_json_dumps(patch["keywords"]))
            if "marks" in patch:
                fields.append("marks_json = ?")
                args.append(_json_dumps(patch["marks"]))
            if fields:
                fields.append("version = version + 1")
                fields.append("analyzed_at = ?")
                fields.append("analyzed_by = ?")
                args.extend([now, patch.get("analyzed_by", "human"), analyzed_id])
                conn.execute(
                    f"UPDATE analyzed_message SET {', '.join(fields)} WHERE id = ?",
                    args,
                )
            if "targets" in patch:
                conn.execute("DELETE FROM impact_target WHERE analyzed_id = ?", (analyzed_id,))
                for i, t in enumerate(patch["targets"] or []):
                    if isinstance(t, dict):
                        conn.execute(
                            """
                            INSERT INTO impact_target (analyzed_id, kind, code, name, sort_order)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                analyzed_id,
                                t.get("kind", "other"),
                                t.get("code"),
                                t.get("name", ""),
                                i,
                            ),
                        )
            conn.commit()
    return get_analyzed(analyzed_id, path=path)


def enqueue_analyze(*, raw_ids: list[str], analyzed_ids: list[str], path: Optional[str] = None) -> list[str]:
    init_db(path)
    db = path or DB_PATH
    now = _now()
    job_ids: list[str] = []
    with _LOCK:
        with closing(_connect(db)) as conn:
            for rid in raw_ids:
                jid = new_id("job")
                conn.execute(
                    """
                    INSERT INTO analyze_job (id, target_type, target_id, status, created_at)
                    VALUES (?, 'raw', ?, 'pending', ?)
                    """,
                    (jid, rid, now),
                )
                job_ids.append(jid)
            for aid in analyzed_ids:
                jid = new_id("job")
                conn.execute(
                    """
                    INSERT INTO analyze_job (id, target_type, target_id, status, created_at)
                    VALUES (?, 'analyzed', ?, 'pending', ?)
                    """,
                    (jid, aid, now),
                )
                job_ids.append(jid)
            conn.commit()
    return job_ids


def list_pending_jobs(limit: int = 20, *, path: Optional[str] = None) -> list[dict[str, Any]]:
    init_db(path)
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            rows = conn.execute(
                """
                SELECT id, target_type, target_id, status, created_at, error
                FROM analyze_job WHERE status = 'pending'
                ORDER BY created_at LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def count_jobs_by_status(*, path: Optional[str] = None) -> dict[str, int]:
    init_db(path)
    db = path or DB_PATH
    with _LOCK:
        with closing(_connect(db)) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM analyze_job GROUP BY status"
            ).fetchall()
    return {r["status"]: int(r["c"]) for r in rows}
