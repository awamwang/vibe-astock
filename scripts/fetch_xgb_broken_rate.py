"""选股宝炸板率离线拉取。

口径：Flash market_indicator/line 的 limit_up_broken_ratio
（与涨停池+炸板池 zb/(zt+zb) 一致）。

落盘：~/.duanxian-agents/cache/xgb_broken_rate/series.json
刷新分位序列时，`sentiment_score` 会读取该文件并入炸板率分量。

用法：
  python scripts/fetch_xgb_broken_rate.py status
  python scripts/fetch_xgb_broken_rate.py backfill --days 220
  python scripts/fetch_xgb_broken_rate.py incr
  python scripts/fetch_xgb_broken_rate.py today
  python scripts/fetch_xgb_broken_rate.py today --date 2026-01-06
  python scripts/fetch_xgb_broken_rate.py watch
  python scripts/fetch_xgb_broken_rate.py today --date 2026-01-06 --interval 0
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_OUT = Path.home() / ".duanxian-agents" / "cache" / "xgb_broken_rate" / "series.json"
LINE_URL = "https://flash-api.xuangubao.cn/api/market_indicator/line"
FIELDS = (
    "market_temperature,limit_up_broken_count,limit_up_broken_ratio,"
    "yesterday_limit_up_avg_pcp,rise_count,fall_count"
)
UA = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://xuangubao.cn/",
}
SCHEMA = 1
SOURCE = "xuangubao.flash.market_indicator"
CALIBER = "limit_up_broken_ratio（选股宝；等同炸板未回封/(涨停+炸板未回封)）"


def now_str() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{now_str()}] {msg}", flush=True)


def china_today() -> str:
    return datetime.now(_TZ).date().isoformat()


def parse_date(s: str) -> str:
    datetime.strptime(s, "%Y-%m-%d")
    return s


def load_store(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "schema": SCHEMA,
            "source": SOURCE,
            "caliber": CALIBER,
            "updated_at": None,
            "rows": [],
        }
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise SystemExit(f"落盘文件格式错误: {path}")
    rows = raw.get("rows") or []
    if not isinstance(rows, list):
        rows = []
    return {
        "schema": int(raw.get("schema") or SCHEMA),
        "source": raw.get("source") or SOURCE,
        "caliber": raw.get("caliber") or CALIBER,
        "updated_at": raw.get("updated_at"),
        "rows": [r for r in rows if isinstance(r, dict) and r.get("date")],
    }


def save_store(path: Path, envelope: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(envelope.get("rows") or [], key=lambda r: r["date"])
    out = {
        "schema": SCHEMA,
        "source": SOURCE,
        "caliber": CALIBER,
        "updated_at": now_str(),
        "rows": rows,
        "meta": {
            "days": len(rows),
            "ok_days": sum(1 for r in rows if r.get("ok") and r.get("broken_rate") is not None),
            "first": rows[0]["date"] if rows else None,
            "last": rows[-1]["date"] if rows else None,
        },
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def rows_by_date(envelope: dict[str, Any]) -> dict[str, dict]:
    return {r["date"]: r for r in (envelope.get("rows") or []) if r.get("date")}


def upsert_row(envelope: dict[str, Any], row: dict[str, Any]) -> None:
    by = rows_by_date(envelope)
    by[row["date"]] = row
    envelope["rows"] = list(by.values())


def jitter_sleep(interval: float, jitter: float) -> None:
    if interval <= 0:
        return
    lo = max(0.0, 1.0 - jitter)
    hi = 1.0 + jitter
    sec = interval * random.uniform(lo, hi)
    log(f"等待 {sec:.1f}s（基准 {interval:.0f}s ±{jitter:.0%}）")
    time.sleep(sec)


def weekday_fallback(end: str, n: int) -> list[str]:
    d = date.fromisoformat(end)
    out: list[str] = []
    guard = 0
    while len(out) < n and guard < n * 4 + 30:
        guard += 1
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


def trade_days(end: str, n: int) -> list[str]:
    try:
        from duanxian.trade_calendar import trade_dates_ending_at

        days = trade_dates_ending_at(end, n)
        if days:
            return days
    except Exception as exc:  # noqa: BLE001
        log(f"交易日历不可用，改用工作日近似: {type(exc).__name__}: {exc}")
    return weekday_fallback(end, n)


def latest_closed_day() -> str:
    try:
        from duanxian.trade_calendar import latest_session

        s = latest_session()
        if s:
            return s
    except Exception:  # noqa: BLE001
        pass
    today = china_today()
    now = datetime.now(_TZ)
    if now.weekday() < 5 and (now.hour, now.minute) >= (15, 5):
        return today
    return weekday_fallback(today, 2)[0]


def fetch_day(day: str, *, timeout: float = 20.0) -> dict[str, Any]:
    import requests

    r = requests.get(
        LINE_URL,
        params={"fields": FIELDS, "date": day},
        headers=UA,
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    points = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(points, list) or not points:
        return {
            "date": day,
            "ok": False,
            "broken_rate": None,
            "broken_count": None,
            "error": "empty_data",
            "fetched_at": now_str(),
            "source": SOURCE,
        }
    last = points[-1] if isinstance(points[-1], dict) else {}
    ratio = last.get("limit_up_broken_ratio")
    count = last.get("limit_up_broken_count")
    try:
        br = float(ratio) if ratio is not None else None
    except (TypeError, ValueError):
        br = None
    try:
        bc = int(count) if count is not None else None
    except (TypeError, ValueError):
        bc = None

    ts = last.get("timestamp")
    ts_day = None
    if isinstance(ts, (int, float)) and ts > 0:
        ts_day = datetime.fromtimestamp(ts, _TZ).date().isoformat()

    ok = br is not None and (ts_day is None or ts_day == day)
    row: dict[str, Any] = {
        "date": day,
        "ok": bool(ok),
        "broken_rate": br,
        "broken_count": bc,
        "temperature": last.get("market_temperature"),
        "rise_count": last.get("rise_count"),
        "fall_count": last.get("fall_count"),
        "yesterday_limit_up_avg_pcp": last.get("yesterday_limit_up_avg_pcp"),
        "timestamp": ts,
        "points": len(points),
        "fetched_at": now_str(),
        "source": SOURCE,
    }
    if ts_day and ts_day != day:
        row["error"] = f"ts_day_mismatch:{ts_day}"
        row["ok"] = False
    return row


def need_fetch(existing: Optional[dict], *, force: bool) -> bool:
    if force:
        return True
    if not existing:
        return True
    if not existing.get("ok"):
        return True
    if existing.get("broken_rate") is None:
        return True
    return False


def run_dates(
    dates: list[str],
    *,
    out: Path,
    interval: float,
    jitter: float,
    force: bool,
    dry_run: bool,
) -> int:
    envelope = load_store(out)
    by = rows_by_date(envelope)
    todo = [d for d in dates if need_fetch(by.get(d), force=force)]
    skip = len(dates) - len(todo)
    log(f"目标 {len(dates)} 日，已有可跳过 {skip}，待拉 {len(todo)} → {out}")
    if dry_run:
        for d in todo[:20]:
            log(f"  dry-run 将拉 {d}")
        if len(todo) > 20:
            log(f"  … 另有 {len(todo) - 20} 日")
        return 0

    ok_n = fail_n = 0
    for i, d in enumerate(todo):
        if i > 0:
            jitter_sleep(interval, jitter)
        try:
            row = fetch_day(d)
        except Exception as exc:  # noqa: BLE001
            row = {
                "date": d,
                "ok": False,
                "broken_rate": None,
                "broken_count": None,
                "error": f"{type(exc).__name__}: {exc}",
                "fetched_at": now_str(),
                "source": SOURCE,
            }
        upsert_row(envelope, row)
        save_store(out, envelope)
        if row.get("ok") and row.get("broken_rate") is not None:
            ok_n += 1
            log(
                f"✓ {d} broken_rate={row['broken_rate']:.4f} "
                f"count={row.get('broken_count')} ({i + 1}/{len(todo)})"
            )
        else:
            fail_n += 1
            log(f"✗ {d} {row.get('error') or 'fail'} ({i + 1}/{len(todo)})")
    log(f"完成：成功 {ok_n}，失败 {fail_n}，文件 {out}")
    return 0 if fail_n == 0 else 2


def cmd_status(args: argparse.Namespace) -> int:
    envelope = load_store(args.out)
    rows = sorted(envelope.get("rows") or [], key=lambda r: r["date"])
    ok_rows = [r for r in rows if r.get("ok") and r.get("broken_rate") is not None]
    miss = [r for r in rows if not (r.get("ok") and r.get("broken_rate") is not None)]
    log(f"文件: {args.out}")
    log(f"口径: {envelope.get('caliber')}")
    log(f"更新: {envelope.get('updated_at') or '—'}")
    log(f"行数: {len(rows)}（有效炸板率 {len(ok_rows)}，失败/空 {len(miss)}）")
    if ok_rows:
        log(f"区间: {ok_rows[0]['date']} → {ok_rows[-1]['date']}")
        last = ok_rows[-1]
        log(
            f"最新: {last['date']} rate={last['broken_rate']:.4f} "
            f"count={last.get('broken_count')}"
        )
    if miss:
        sample = ", ".join(r["date"] for r in miss[:8])
        log(f"待重试样例: {sample}" + ("…" if len(miss) > 8 else ""))
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    end = args.end or latest_closed_day()
    days = trade_days(end, args.days)
    if args.newest_first:
        days = list(reversed(days))
    log(f"backfill end={end} days={args.days} → {len(days)} 个交易日候选")
    return run_dates(
        days,
        out=args.out,
        interval=args.interval,
        jitter=args.jitter,
        force=args.force,
        dry_run=args.dry_run,
    )


def cmd_incr(args: argparse.Namespace) -> int:
    envelope = load_store(args.out)
    ok_rows = [
        r
        for r in (envelope.get("rows") or [])
        if r.get("ok") and r.get("broken_rate") is not None and r.get("date")
    ]
    end = args.end or latest_closed_day()
    if not ok_rows:
        log("库内无有效日，改走 backfill")
        args.days = args.days or 220
        args.newest_first = False
        return cmd_backfill(args)

    last = max(r["date"] for r in ok_rows)
    window = trade_days(end, max(args.days or 260, 260))
    todo = [d for d in window if d > last]
    force = bool(args.force)
    if args.include_last:
        todo = [d for d in window if d >= last]
        force = True
    if not todo:
        log(f"已最新：last={last} end={end}，无增量")
        return 0
    log(f"incr last={last} end={end} 待补 {len(todo)} 日")
    return run_dates(
        todo,
        out=args.out,
        interval=args.interval,
        jitter=args.jitter,
        force=force,
        dry_run=args.dry_run,
    )


def cmd_today(args: argparse.Namespace) -> int:
    day = args.date or china_today()
    parse_date(day)
    return run_dates(
        [day],
        out=args.out,
        interval=0,
        jitter=0,
        force=True,
        dry_run=args.dry_run,
    )


def cmd_watch(args: argparse.Namespace) -> int:
    log(
        f"watch 开始：每轮刷新今日，间隔 {args.interval:.0f}s ±{args.jitter:.0%}；Ctrl+C 结束"
    )
    while True:
        day = args.date or china_today()
        code = run_dates(
            [day],
            out=args.out,
            interval=0,
            jitter=0,
            force=True,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            return code
        try:
            jitter_sleep(args.interval, args.jitter)
        except KeyboardInterrupt:
            log("已停止 watch")
            return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--out",
        type=Path,
        default=Path(os.environ.get("XGB_BROKEN_RATE_OUT") or DEFAULT_OUT),
        help=f"落盘 JSON（默认 {DEFAULT_OUT}）",
    )
    common.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="连续请求间隔秒数（默认 60）",
    )
    common.add_argument(
        "--jitter",
        type=float,
        default=0.10,
        help="间隔相对抖动比例（默认 0.10 = ±10%%）",
    )
    common.add_argument("--force", action="store_true", help="已有有效数据也重拉")
    common.add_argument("--dry-run", action="store_true", help="只列待拉日期，不请求")

    p = argparse.ArgumentParser(
        description="选股宝炸板率离线拉取（历史补齐 / 增量 / 新数据，不进业务系统）",
        parents=[common],
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status", parents=[common], help="查看落盘覆盖")
    sp.set_defaults(func=cmd_status)

    bp = sub.add_parser("backfill", parents=[common], help="补足最近 N 个交易日缺口")
    bp.add_argument("--days", type=int, default=220, help="交易日窗口（默认 220）")
    bp.add_argument("--end", default=None, help="窗口终点 YYYY-MM-DD（默认最近已收盘日）")
    bp.add_argument(
        "--newest-first",
        action="store_true",
        help="从近到远拉（默认从远到近，利于先补齐历史）",
    )
    bp.set_defaults(func=cmd_backfill)

    ip = sub.add_parser("incr", parents=[common], help="从库内最后有效日之后增量补齐")
    ip.add_argument("--days", type=int, default=260, help="向前扫描窗（默认 260）")
    ip.add_argument("--end", default=None, help="增量终点（默认最近已收盘日）")
    ip.add_argument(
        "--include-last",
        action="store_true",
        help="连最后一日一并重拉（适合收盘后定稿）",
    )
    ip.set_defaults(func=cmd_incr)

    tp = sub.add_parser("today", parents=[common], help="拉/刷新单日新数据")
    tp.add_argument("--date", default=None, help="YYYY-MM-DD，默认日历今天")
    tp.set_defaults(func=cmd_today)

    wp = sub.add_parser("watch", parents=[common], help="循环刷新今日新数据")
    wp.add_argument("--date", default=None, help="固定刷新某日；默认每天用日历今天")
    wp.set_defaults(func=cmd_watch)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.interval < 0 or args.jitter < 0:
        log("interval/jitter 不能为负")
        return 1
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
