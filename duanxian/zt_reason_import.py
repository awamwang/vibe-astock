"""同花顺涨停原因 txt 导入。

把同花顺行情导出的涨停池文本解析成「6 位代码 → 涨停原因题材串」，
落一份解析快照，再写入题材事件树使用的 `zt_reasons` 缓存。
首板分析读的是同一份缓存，因此不配问财密钥时也能用题材串。

同花顺导出经常是「列与列之间双 Tab、个别列又是单 Tab」，按表头下标会对错列。
这里按单元格内容定位：代码 →（名称）→ 涨幅 → 现价 → 涨停原因类别。
没有涨停原因（`--` / 空）的行直接跳过，不报错。
"""

from __future__ import annotations

import os
import re
from typing import Optional

from .util import atomic_write_json, china_now
from . import paths as _paths

_IMPORT_DIR = ""


@_paths.register_rebind
def _rebind_paths() -> None:
    global _IMPORT_DIR
    _IMPORT_DIR = str(_paths.agents_dir() / 'cache' / 'zt_reasons_import')

_DATE_IN_COL = re.compile(r"\[(\d{8})\]")
_CODE_TOKEN = re.compile(r"^(?:SH|SZ|BJ)(\d{6})$", re.I)
_TIME = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
_CHG = re.compile(r"^[+-]\d+(?:\.\d+)?%?$")
_PRICE = re.compile(r"^\d+(?:\.\d+)+$")
_MARKER = re.compile(r"^\d{1,3}$")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_EMPTY = {"", "--", "-", "—", "nan", "none", "null", "无"}

# 这些列名上的日期才是导出场次；「涨停原因类别[20250324]」里的日期经常是模板遗留。
_DATE_PRIORITY = ("首次涨停时间", "最终涨停时间", "涨停开板次数", "涨停封单量", "概念龙头")


class ZtReasonImportError(ValueError):
    """同花顺涨停原因文本无法解析。"""


def _split_ths_line(line: str) -> list[str]:
    """按列切开一行。优先 tab（同花顺导出原样）；没有 tab 时按连续空格切。"""
    line = line.rstrip("\r\n")
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    return [c.strip() for c in re.split(r"[ \u3000]{2,}", line)]


def _compact(cols: list[str]) -> list[str]:
    return [c for c in cols if c]


def _norm_col(name: str) -> str:
    return _DATE_IN_COL.sub("", name or "").strip()


def _infer_date(headers: list[str]) -> Optional[str]:
    """从表头列名推断导出场次（YYYYMMDD）。"""
    for key in _DATE_PRIORITY:
        for h in headers:
            if key in h:
                m = _DATE_IN_COL.search(h)
                if m:
                    return m.group(1)
    votes: dict[str, int] = {}
    for h in headers:
        if "涨停原因" in h:
            continue
        m = _DATE_IN_COL.search(h)
        if m:
            votes[m.group(1)] = votes.get(m.group(1), 0) + 1
    if votes:
        return max(votes, key=votes.get)
    return None


def _to_iso(ymd: str) -> str:
    d = str(ymd).replace("/", "-").replace(".", "-").strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d


def _is_header(cols: list[str]) -> bool:
    blob = "".join(cols)
    return "代码" in blob and ("涨停原因" in blob or "名称" in blob)


def _is_name(text: str) -> bool:
    if not text or text.startswith("【") or "+" in text:
        return False
    if text.startswith(("+", "-")) or _TIME.match(text):
        return False
    return bool(_HAN.search(text))


def _is_real_reason(text: str) -> bool:
    """涨停原因类别：含中文的短题材串。数字 / 时间 / -- / 所属概念 都不算。"""
    s = (text or "").strip()
    if not s or s.lower() in _EMPTY:
        return False
    if s.startswith("【") or s.endswith("】"):
        return False
    if _TIME.match(s) or _MARKER.fullmatch(s) or _PRICE.fullmatch(s) or _CHG.match(s):
        return False
    return bool(_HAN.search(s))


def _normalize_reason(text: str) -> str:
    """统一分隔符。涨停原因类别本身已是短串，不去截断。"""
    text = (text or "").strip()
    if text.lower() in _EMPTY:
        return ""
    text = (text.replace("，", "+").replace(",", "+")
            .replace(";", "+").replace("；", "+"))
    tags = [t.strip() for t in text.split("+") if t.strip() and t.strip().lower() not in _EMPTY]
    return "+".join(tags)


def _looks_boards(text: str) -> bool:
    return bool(_MARKER.fullmatch(text)) and 0 <= int(text) <= 30


def _extract_row(cols: list[str]) -> Optional[dict]:
    """从一行单元格里取出代码 / 名称 / 涨停原因。对不上或没有原因返回 None。"""
    compact = _compact(cols)
    if not compact or _is_header(compact):
        return None

    code_i, code = None, ""
    for i, cell in enumerate(compact):
        m = _CODE_TOKEN.match(cell)
        if m:
            code_i, code = i, m.group(1)
            break
        # 纯 6 位：避免把金额里的数字当代码，只在后面紧跟名称时认
        m6 = re.fullmatch(r"\d{6}", cell)
        if m6 and i + 1 < len(compact) and _is_name(compact[i + 1]):
            code_i, code = i, m6.group(0)
            break
    if code_i is None:
        return None

    name = ""
    j = code_i + 1
    if j < len(compact) and _is_name(compact[j]):
        name = compact[j]
        j += 1
    # 「.」列有时会写出一个短数字标记
    if j < len(compact) and _MARKER.fullmatch(compact[j]) and j + 1 < len(compact) and _CHG.match(compact[j + 1]):
        j += 1
    if j < len(compact) and _CHG.match(compact[j]):
        j += 1
    if j < len(compact) and _PRICE.fullmatch(compact[j]):
        j += 1

    reason_raw = compact[j] if j < len(compact) else ""
    if not _is_real_reason(reason_raw):
        # 表头下标对不齐时：找「题材串 + 连板天数 + 首次涨停时间」
        reason_raw = ""
        for i in range(code_i + 1, len(compact) - 1):
            nxt = compact[i + 1]
            nxt2 = compact[i + 2] if i + 2 < len(compact) else ""
            if _looks_boards(nxt) and (_TIME.match(nxt2) or nxt2 in _EMPTY):
                cand = compact[i]
                if _is_real_reason(cand):
                    reason_raw = cand
                    break
                return None  # 对上了结构但原因是 -- / 空 → 忽略这行
        if not reason_raw:
            for cell in compact[code_i + 1:]:
                if _is_real_reason(cell) and cell != name:
                    reason_raw = cell
                    break
        if not _is_real_reason(reason_raw):
            return None

    reason = _normalize_reason(reason_raw)
    if not reason:
        return None
    return {"code": code, "name": name, "reason": reason}


def parse_ths_limit_up_txt(text: str, fallback_date: Optional[str] = None) -> dict:
    """解析同花顺涨停池 txt。没有涨停原因的行会被跳过。"""
    text = (text or "").lstrip("\ufeff")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ZtReasonImportError("文本为空")

    header_idx = None
    header: list[str] = []
    for i, ln in enumerate(lines[:20]):
        cols = _split_ths_line(ln)
        if _is_header(cols):
            header_idx = i
            header = _compact(cols)
            break
    if header_idx is None:
        raise ZtReasonImportError("找不到表头（需要含「代码」和「涨停原因」的一行）")

    has_reason_col = any("涨停原因" in h for h in header)
    ymd = _infer_date(header) or (
        str(fallback_date).replace("-", "") if fallback_date else None)
    if not ymd or len(ymd) != 8 or not ymd.isdigit():
        raise ZtReasonImportError("无法从表头识别交易日，且没有可回退的日期")

    reasons: dict[str, str] = {}
    rows: list[dict] = []
    skipped = 0
    locate_hint = ""
    for ln in lines[header_idx + 1:]:
        cols = _split_ths_line(ln)
        if _is_header(cols):
            continue
        hit = _extract_row(cols)
        if hit is None:
            compact = _compact(cols)
            if any(_CODE_TOKEN.match(c) for c in compact):
                skipped += 1
                if not locate_hint:
                    locate_hint = "、".join(compact[:10])
            continue
        reasons[hit["code"]] = hit["reason"]
        rows.append(hit)

    if not reasons:
        extra = f" 已定位到表头「涨停原因」列。" if has_reason_col else " 表头里没有看到「涨停原因」列。"
        if locate_hint:
            extra += f" 首条股票行有效单元格：{locate_hint}"
        raise ZtReasonImportError("没有解析到任何涨停原因（无原因的行已忽略）。" + extra)

    return {
        "date": _to_iso(ymd),
        "date_ymd": ymd,
        "header": header,
        "reasons": reasons,
        "rows": rows,
        "skipped": skipped,
    }


def _save_snapshot(text: str, parsed: dict) -> tuple[str, str]:
    iso = parsed["date"]
    os.makedirs(_IMPORT_DIR, exist_ok=True)
    snapshot = {
        "date": iso,
        "imported_at": china_now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(parsed["reasons"]),
        "skipped": parsed["skipped"],
        "header": parsed["header"],
        "rows": parsed["rows"],
    }
    snap_path = os.path.join(_IMPORT_DIR, f"{iso}.json")
    if not atomic_write_json(snap_path, snapshot):
        raise ZtReasonImportError(f"写入解析快照失败：{snap_path}")
    raw_path = os.path.join(_IMPORT_DIR, f"{iso}.txt")
    try:
        with open(raw_path, "w", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
    except OSError as exc:
        raise ZtReasonImportError(f"写入原始文本失败：{raw_path}") from exc
    return snap_path, raw_path


def parse_preview(text: str, fallback_date: Optional[str] = None) -> dict:
    """只解析并落临时快照，不写入题材串缓存。"""
    parsed = parse_ths_limit_up_txt(text, fallback_date=fallback_date)
    snap_path, raw_path = _save_snapshot(text, parsed)
    return {
        "ok": True,
        "date": parsed["date"],
        "date_ymd": parsed["date_ymd"],
        "count": len(parsed["rows"]),
        "skipped": parsed["skipped"],
        "rows": [{"code": r["code"], "name": r["name"], "reason": r["reason"]} for r in parsed["rows"]],
        "snapshot": snap_path,
        "raw": raw_path,
        "reasons": parsed["reasons"],
    }


def import_ths_text(text: str, fallback_date: Optional[str] = None) -> dict:
    """解析、落临时快照，并把题材串写入系统缓存。"""
    parsed = parse_ths_limit_up_txt(text, fallback_date=fallback_date)
    snap_path, raw_path = _save_snapshot(text, parsed)
    iso = parsed["date"]

    from . import theme_tree as tt

    # 整份导出覆盖当天题材串，避免上次错列解析留下的脏数据混进来
    cache_path = tt.save_reasons(iso, parsed["reasons"], source="ths_import")

    return {
        "ok": True,
        "date": iso,
        "date_ymd": parsed["date_ymd"],
        "count": len(parsed["reasons"]),
        "imported": len(parsed["reasons"]),
        "skipped": parsed["skipped"],
        "snapshot": snap_path,
        "raw": raw_path,
        "cache": cache_path,
        "reasons": parsed["reasons"],
        "rows": [{"code": r["code"], "name": r["name"], "reason": r["reason"]} for r in parsed["rows"]],
    }
