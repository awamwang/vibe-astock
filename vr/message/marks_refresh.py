"""未归档消息 marks 重算（启动时后台执行一次）。"""

from __future__ import annotations

import logging
import threading
from contextlib import closing
from typing import Any

from . import cls, store, xgb
from .schemas import RawMessage

_log = logging.getLogger(__name__)

_SCHEDULE_LOCK = threading.Lock()
_SCHEDULED = False

_BATCH = 200


def strip_level_marks(marks: list[str] | None) -> list[str]:
    """去掉财联社 level:a/b/c 标记，保留其余。"""
    out: list[str] = []
    for m in marks or []:
        s = str(m or "").strip()
        if not s:
            continue
        if s.lower() in ("level:a", "level:b", "level:c"):
            continue
        out.append(s)
    return list(dict.fromkeys(out))


def derive_marks_from_raw(raw: RawMessage) -> list[str]:
    """按来源原始字段重算 marks；无原始字段时仅剥离 level:a/b/c。"""
    meta = raw.meta if isinstance(raw.meta, dict) else {}
    if raw.source_id == "cls_telegraph":
        cls_raw = meta.get("cls_raw")
        if isinstance(cls_raw, dict):
            return cls.derive_marks(cls_raw)
        return strip_level_marks(raw.marks)
    if raw.source_id == "xgb_msgs":
        xgb_raw = meta.get("xgb_raw")
        if isinstance(xgb_raw, dict):
            return xgb.derive_marks(xgb_raw)
        return strip_level_marks(raw.marks)
    return strip_level_marks(raw.marks)


def _marks_equal(a: list[str], b: list[str]) -> bool:
    return list(a or []) == list(b or [])


def _merge_marks(parts: list[list[str]]) -> list[str]:
    merged: list[str] = []
    for marks in parts:
        for m in marks:
            if m not in merged:
                merged.append(m)
    return merged


def refresh_marks(*, path: str | None = None) -> dict[str, Any]:
    """重算主库（未归档）raw / analyzed 的 marks，返回统计。"""
    store.init_db(path)
    db = path or store.DB_PATH
    scanned_raw = 0
    updated_raw = 0
    scanned_analyzed = 0
    updated_analyzed = 0
    offset = 0

    while True:
        with store._LOCK:
            with closing(store._connect(db)) as conn:
                rows = conn.execute(
                    """
                    SELECT id, source_id, source_label, content, title, keywords_json, url,
                           marks_json, content_hash, batch_id, external_ref, produced_at,
                           ingested_at, meta_json, withdrawn
                    FROM raw_message
                    WHERE withdrawn = 0
                    ORDER BY ingested_at ASC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (_BATCH, offset),
                ).fetchall()
                if not rows:
                    break
                for r in rows:
                    scanned_raw += 1
                    raw = store._row_raw(r)
                    new_marks = derive_marks_from_raw(raw)
                    if _marks_equal(raw.marks, new_marks):
                        continue
                    conn.execute(
                        "UPDATE raw_message SET marks_json = ? WHERE id = ?",
                        (store._json_dumps(new_marks), raw.id),
                    )
                    updated_raw += 1
                conn.commit()
        n = len(rows)
        offset += n
        if n < _BATCH:
            break

    offset = 0
    while True:
        with store._LOCK:
            with closing(store._connect(db)) as conn:
                rows = conn.execute(
                    """
                    SELECT id, marks_json FROM analyzed_message
                    ORDER BY analyzed_at ASC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (_BATCH, offset),
                ).fetchall()
                if not rows:
                    break
                for r in rows:
                    scanned_analyzed += 1
                    aid = r["id"]
                    old_marks = store._json_loads(r["marks_json"], [])
                    link_rows = conn.execute(
                        """
                        SELECT id, source_id, source_label, content, title, keywords_json, url,
                               marks_json, content_hash, batch_id, external_ref, produced_at,
                               ingested_at, meta_json, withdrawn
                        FROM raw_message
                        WHERE id IN (
                            SELECT raw_id FROM raw_analyzed_link WHERE analyzed_id = ?
                        ) AND withdrawn = 0
                        """,
                        (aid,),
                    ).fetchall()
                    if link_rows:
                        parts = [derive_marks_from_raw(store._row_raw(lr)) for lr in link_rows]
                        new_marks = _merge_marks(parts)
                    else:
                        new_marks = strip_level_marks(old_marks)
                    if _marks_equal(old_marks, new_marks):
                        continue
                    conn.execute(
                        "UPDATE analyzed_message SET marks_json = ? WHERE id = ?",
                        (store._json_dumps(new_marks), aid),
                    )
                    updated_analyzed += 1
                conn.commit()
        n = len(rows)
        offset += n
        if n < _BATCH:
            break

    return {
        "scanned_raw": scanned_raw,
        "updated_raw": updated_raw,
        "scanned_analyzed": scanned_analyzed,
        "updated_analyzed": updated_analyzed,
    }


def schedule_refresh_marks(*, path: str | None = None) -> bool:
    """启动时异步重算一次；已调度则跳过。不阻塞调用方。"""
    global _SCHEDULED
    with _SCHEDULE_LOCK:
        if _SCHEDULED:
            return False
        _SCHEDULED = True

    def _run() -> None:
        try:
            stats = refresh_marks(path=path)
            _log.info(
                "消息 marks 重算完成 raw=%s/%s analyzed=%s/%s",
                stats["updated_raw"],
                stats["scanned_raw"],
                stats["updated_analyzed"],
                stats["scanned_analyzed"],
            )
        except Exception:  # noqa: BLE001
            _log.exception("消息 marks 重算失败")

    threading.Thread(target=_run, daemon=True, name="message-marks-refresh").start()
    return True
