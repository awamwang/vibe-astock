"""交易经验记忆库 —— 主题 Markdown + index.md，供本页问答 / 全局问 AI / 外部 Agent 调取。

落盘：`~/.duanxian-agents/experience/`
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any, Optional

from .util import china_now, china_today, safe_join

from . import paths as _paths

DIR = ""


@_paths.register_rebind
def _rebind_paths() -> None:
    global DIR
    DIR = str(_paths.agents_dir() / "experience")


INDEX_NAME = "index.md"
_LOCK = threading.Lock()

_RESERVED = frozenset({INDEX_NAME.lower(), "readme.md"})
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TOPIC_LINE = re.compile(
    r"^-\s+\*\*(?P<title>.+?)\*\*\s*[|｜]\s*`(?P<file>[^`]+)`\s*[—\-–]\s*(?P<summary>.*)\s*$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_SUFFIX = re.compile(r"-(\d{4}-\d{2}-\d{2})$")

CATEGORIES = ("踩坑", "操作指引", "方法论", "盘感复盘", "仓位纪律")
DEFAULT_CATEGORY = "方法论"
_CATEGORY_ALIASES = (
    ("踩坑", "踩坑"),
    ("教训", "踩坑"),
    ("错误", "踩坑"),
    ("操作指引", "操作指引"),
    ("指引", "操作指引"),
    ("打法", "操作指引"),
    ("方法论", "方法论"),
    ("框架", "方法论"),
    ("盘感复盘", "盘感复盘"),
    ("盘感", "盘感复盘"),
    ("复盘", "盘感复盘"),
    ("仓位纪律", "仓位纪律"),
    ("仓位", "仓位纪律"),
    ("纪律", "仓位纪律"),
    ("风控", "仓位纪律"),
)


def ensure_dir(root: Optional[str] = None) -> str:
    """确保经验库目录存在，返回绝对路径。"""
    path = os.path.abspath(root or DIR)
    os.makedirs(path, exist_ok=True)
    return path


def root_path(root: Optional[str] = None) -> str:
    return ensure_dir(root)


def sanitize_filename(name: str) -> str:
    """主题名 → 安全的中文 `.md` 文件名。"""
    raw = (name or "").strip()
    if raw.lower().endswith(".md"):
        raw = raw[:-3].strip()
    raw = _BAD_CHARS.sub("", raw).replace("..", "").strip(" .")
    if not raw:
        raw = "未命名主题"
    filename = f"{raw}.md"
    if filename.lower() in _RESERVED:
        filename = f"{raw}-记忆.md"
    return filename


def normalize_date(value: Optional[str]) -> str:
    day = (value or "").strip()
    if _DATE_RE.fullmatch(day):
        return day
    return china_today()


def suffix_title_date(title: str, date: str) -> str:
    """标题去掉旧日期后缀后，再拼上 YYYY-MM-DD。"""
    raw = (title or "").strip() or "未命名主题"
    if raw.lower().endswith(".md"):
        raw = raw[:-3].strip()
    m = _DATE_SUFFIX.search(raw)
    if m:
        raw = raw[: m.start()].rstrip()
    day = normalize_date(date)
    return f"{raw}-{day}"


def dated_filename(title: str, date: Optional[str] = None) -> str:
    """标题 + 日期 → 文件名（如 `连板掉下来宁可等二波-2026-09-17.md`）。"""
    day = normalize_date(date)
    return sanitize_filename(suffix_title_date(title, day))


def normalize_category(raw: Any) -> str:
    s = str(raw or "").strip()
    if s in CATEGORIES:
        return s
    for key, cat in _CATEGORY_ALIASES:
        if key and key in s:
            return cat
    return DEFAULT_CATEGORY


def _topic_path(filename: str, root: Optional[str] = None) -> str:
    base = ensure_dir(root)
    name = os.path.basename(filename.strip())
    if not name.lower().endswith(".md"):
        name = f"{name}.md"
    if name.lower() in _RESERVED:
        raise ValueError(f"保留文件名不可用作主题：{name}")
    if _BAD_CHARS.search(name[:-3]) or ".." in name:
        raise ValueError(f"非法主题文件名：{name}")
    return safe_join(base, name)


def _read_text(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _atomic_write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def parse_index(text: str) -> list[dict[str, str]]:
    """解析 index.md 主题列表。"""
    topics: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        m = _TOPIC_LINE.match(line.strip())
        if not m:
            continue
        filename = os.path.basename(m.group("file").strip())
        if not filename.lower().endswith(".md"):
            filename = f"{filename}.md"
        key = filename.lower()
        if key in _RESERVED or key in seen:
            continue
        seen.add(key)
        topics.append({
            "filename": filename,
            "title": m.group("title").strip() or filename[:-3],
            "summary": m.group("summary").strip(),
        })
    return topics


def build_index(topics: list[dict[str, str]], root: Optional[str] = None) -> str:
    """生成 index.md 全文。"""
    base = root_path(root)
    lines = [
        "# 经验记忆索引",
        "",
        f"> 库根路径：`{base}`",
        "> 供外部 Agent / 本应用问答检索。确认写入后自动更新。",
        "",
        f"_更新于 {china_now().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        "## 主题",
        "",
    ]
    if not topics:
        lines.append("_（暂无主题）_")
    else:
        for t in topics:
            title = (t.get("title") or "").strip() or t["filename"][:-3]
            summary = (t.get("summary") or "").strip() or "（无摘要）"
            lines.append(f"- **{title}** | `{t['filename']}` — {summary}")
    lines.append("")
    return "\n".join(lines)


def list_topic_files(root: Optional[str] = None) -> list[str]:
    base = ensure_dir(root)
    names = []
    for name in sorted(os.listdir(base)):
        if not name.lower().endswith(".md"):
            continue
        if name.lower() in _RESERVED:
            continue
        if os.path.isfile(os.path.join(base, name)):
            names.append(name)
    return names


def load_index_topics(root: Optional[str] = None) -> list[dict[str, str]]:
    """读 index；若缺失则按目录扫描补齐。"""
    base = ensure_dir(root)
    index_path = os.path.join(base, INDEX_NAME)
    topics = parse_index(_read_text(index_path))
    by_name = {t["filename"].lower(): t for t in topics}
    for name in list_topic_files(base):
        if name.lower() in by_name:
            continue
        topics.append({"filename": name, "title": name[:-3], "summary": ""})
    return topics


def _ensure_vr() -> None:
    from . import vr_host as vh

    vh._add_vr_to_path()


def _ai_targets(raw_stocks: list[Any], raw_sectors: list[Any]) -> list[dict[str, Any]]:
    """把 AI 抽出的个股/板块收成消息分析同款 targets。"""
    from . import articles as arts

    items: list[dict[str, Any]] = []
    for row in raw_stocks or []:
        q = arts._norm_stock_query(row)
        if not q:
            continue
        items.append({
            "kind": "stock",
            "code": q.get("code"),
            "name": q.get("name") or "",
        })
    for row in raw_sectors or []:
        if isinstance(row, dict):
            name = str(row.get("name") or row.get("raw") or "").strip()
        else:
            name = str(row or "").strip()
        if name:
            items.append({"kind": "sector", "code": None, "name": name})
    try:
        from vr.message.content_targets import fill_target_stock_codes

        return fill_target_stock_codes(items)
    except Exception:  # noqa: BLE001
        return items


def _split_targets(targets: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stocks: list[dict[str, Any]] = []
    sectors: list[dict[str, Any]] = []
    seen_stock: set[str] = set()
    seen_sector: set[str] = set()
    for raw in targets or []:
        if hasattr(raw, "model_dump"):
            d = raw.model_dump()
        elif isinstance(raw, dict):
            d = raw
        else:
            continue
        kind = str(d.get("kind") or "")
        name = str(d.get("name") or "").strip()
        code = str(d.get("code") or "").strip() or None
        if kind == "stock":
            key = f"{code or ''}|{name}"
            if key in seen_stock or (not code and not name):
                continue
            seen_stock.add(key)
            stocks.append({"code": code, "name": name or code})
        elif kind in ("sector", "theme"):
            if not name or name in seen_sector:
                continue
            seen_sector.add(name)
            sectors.append({"name": name, "code": code})
    return stocks, sectors


def _feed_unmatched_targets(targets: list[Any]) -> None:
    """未匹配成个股的名称喂入板块待匹配（对齐消息分析 feed_message_targets）。"""
    names: list[str] = []
    try:
        _ensure_vr()
        import stock_processor  # noqa: PLC0415
        from ths_block import processor as block_processor  # noqa: PLC0415

        for raw in targets or []:
            d = raw.model_dump() if hasattr(raw, "model_dump") else (raw if isinstance(raw, dict) else {})
            name = str(d.get("name") or "").strip()
            code = str(d.get("code") or "").strip() or None
            if not name and not code:
                continue
            hit = stock_processor.resolve_one(code=code, name=name or None)
            if hit.get("status") == "matched":
                continue
            if name:
                names.append(name)
        if names:
            block_processor.feed("experience", names)
    except Exception:  # noqa: BLE001
        pass


def resolve_experience_targets(
    *,
    text: str,
    raw_stocks: list[Any] | None = None,
    raw_sectors: list[Any] | None = None,
    feed: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """消息分析口径：AI 抽出的标的在前，再扫描正文增量合并。"""
    existing = _ai_targets(raw_stocks or [], raw_sectors or [])
    try:
        _ensure_vr()
        from vr.message.content_targets import enrich_targets_from_content, fill_target_stock_codes

        merged = enrich_targets_from_content(
            text or "",
            existing=existing,
            feed_unmatched=feed,
            feed_source="experience",
        )
        filled = fill_target_stock_codes(merged)
    except Exception:  # noqa: BLE001
        filled = existing
    if feed:
        _feed_unmatched_targets(filled)
    return _split_targets(filled)


_KIND_TAIL_RE = re.compile(
    r"[（(](?:概念|行业|地域|自定义|热点主题|每日动态|未匹配)[）)]$"
)


def _parse_stock_label(raw: str) -> dict[str, Any] | None:
    s = (raw or "").strip()
    if not s or s == "（无）":
        return None
    s = _KIND_TAIL_RE.sub("", s).strip()
    m = re.match(r"^(\d{6})\s+(.+)$", s)
    if m:
        return {"code": m.group(1), "name": m.group(2).strip()}
    try:
        from vr.message.content_targets import _split_embedded_code

        name, code = _split_embedded_code(s, None)
    except Exception:  # noqa: BLE001
        name, code = s, None
    if not name and not code:
        return None
    return {"code": code, "name": name or code}


def _parse_sector_label(raw: str) -> dict[str, Any] | None:
    s = (raw or "").strip()
    if not s or s == "（无）":
        return None
    s = _KIND_TAIL_RE.sub("", s).strip()
    try:
        from vr.message.content_targets import _split_embedded_code

        name, _code = _split_embedded_code(s, None)
    except Exception:  # noqa: BLE001
        name = s
    name = (name or s).strip()
    return {"name": name} if name else None


def _format_stocks_line(stocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for s in stocks or []:
        nested = s.get("stock") if isinstance(s.get("stock"), dict) else None
        if nested:
            code = str(nested.get("code") or "").strip()
            name = str(nested.get("name") or "").strip()
        else:
            code = str(s.get("code") or "").strip()
            name = str(s.get("name") or "").strip()
        if code and name:
            parts.append(f"{name}({code})")
        elif name or code:
            parts.append(name or code)
    return "；".join(parts) if parts else "（无）"


def _format_sectors_line(sectors: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for s in sectors or []:
        block = s.get("block") if isinstance(s.get("block"), dict) else None
        if block:
            name = str(block.get("name") or "").strip()
        else:
            name = str(s.get("name") or s.get("mapped") or s.get("raw") or "").strip()
        name = _KIND_TAIL_RE.sub("", name).strip()
        if name:
            parts.append(name)
    return "；".join(parts) if parts else "（无）"


def _parse_meta_list(line: str, prefix: str) -> list[str]:
    from . import articles as arts

    return arts._parse_meta_list(line, prefix)


def _strip_body_wrapper(content: str, title: str) -> str:
    """取出「## 正文」之后的内容；否则去掉与标题重复的首行 H1 及元数据行。"""
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    marker = "## 正文"
    idx = text.find(marker)
    if idx >= 0:
        return text[idx + len(marker):].lstrip("\n").strip()
    lines = text.splitlines()
    if not lines:
        return ""
    i = 0
    if lines[0].startswith("# "):
        heading = lines[0][2:].strip()
        base = _DATE_SUFFIX.sub("", title).rstrip()
        heading_base = _DATE_SUFFIX.sub("", heading).rstrip()
        if heading == title or heading == base or heading_base == base:
            i = 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    meta_prefixes = ("- 日期：", "- 分类：", "- 摘要：", "- 个股：", "- 板块：")
    stripped_meta = False
    while i < len(lines) and lines[i].startswith(meta_prefixes):
        stripped_meta = True
        i += 1
    if stripped_meta:
        while i < len(lines) and not lines[i].strip():
            i += 1
    return "\n".join(lines[i:]).strip()


def build_experience_markdown(
    *,
    title: str,
    date: str,
    category: str,
    summary: str,
    body: str,
    stocks: list[dict[str, Any]],
    sectors: list[dict[str, Any]],
) -> str:
    """组装落盘 Markdown：元数据 + 整理后的正文。"""
    lines = [
        f"# {title}",
        "",
        f"- 日期：{date}",
        f"- 分类：{category}",
        f"- 摘要：{summary}",
        f"- 个股：{_format_stocks_line(stocks)}",
        f"- 板块：{_format_sectors_line(sectors)}",
        "",
        "## 正文",
        "",
        (body or "").strip(),
        "",
    ]
    return "\n".join(lines)


def _parse_experience_body(content: str) -> dict[str, Any]:
    """从已落盘正文反解元数据（尽力而为）。"""
    title = ""
    date = ""
    category = ""
    summary = ""
    stock_labels: list[str] = []
    sector_labels: list[str] = []
    for line in (content or "").splitlines()[:40]:
        s = line.strip()
        if s.startswith("# ") and not title:
            title = s[2:].strip()
            continue
        if s.startswith("- 日期："):
            date = s[5:].strip()
        elif s.startswith("- 分类："):
            category = s[5:].strip()
        elif s.startswith("- 摘要："):
            summary = s[5:].strip()
        elif s.startswith("- 个股："):
            stock_labels = _parse_meta_list(s, "- 个股：")
        elif s.startswith("- 板块："):
            sector_labels = _parse_meta_list(s, "- 板块：")
    stocks = [x for x in (_parse_stock_label(s) for s in stock_labels) if x]
    sectors = [x for x in (_parse_sector_label(s) for s in sector_labels) if x]
    return {
        "title": title,
        "date": date,
        "category": category,
        "summary": summary,
        "stocks": stocks,
        "sectors": sectors,
        "body": _strip_body_wrapper(content, title),
    }


def _public_topic(meta: dict[str, str], path: str, content: Optional[str] = None) -> dict[str, Any]:
    body = content if content is not None else _read_text(path)
    parsed = _parse_experience_body(body)
    stocks = parsed.get("stocks") or []
    sectors = parsed.get("sectors") or []
    if not stocks and not sectors:
        text = "\n".join(filter(None, [
            parsed.get("title") or "",
            parsed.get("summary") or "",
            parsed.get("body") or "",
        ]))
        stocks, sectors = resolve_experience_targets(
            text=text,
            raw_stocks=[],
            raw_sectors=[],
            feed=False,
        )
    return {
        "filename": meta["filename"],
        "title": meta.get("title") or parsed.get("title") or meta["filename"][:-3],
        "summary": meta.get("summary") or parsed.get("summary") or "",
        "date": parsed.get("date") or "",
        "category": parsed.get("category") or "",
        "stocks": stocks,
        "sectors": sectors,
    }


def list_topics_for_api(root: Optional[str] = None) -> list[dict[str, Any]]:
    base = ensure_dir(root)
    rows: list[dict[str, Any]] = []
    for t in load_index_topics(base):
        path = os.path.join(base, t["filename"])
        rows.append(_public_topic(t, path))
    return rows


def get_meta(root: Optional[str] = None) -> dict[str, Any]:
    base = root_path(root)
    return {
        "root": base,
        "index_path": os.path.join(base, INDEX_NAME),
        "topics": list_topics_for_api(base),
        "categories": list(CATEGORIES),
    }


def read_topic(filename: str, root: Optional[str] = None) -> dict[str, Any]:
    path = _topic_path(filename, root)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"主题不存在：{os.path.basename(path)}")
    name = os.path.basename(path)
    topics = {t["filename"].lower(): t for t in load_index_topics(root)}
    meta = topics.get(name.lower(), {})
    content = _read_text(path)
    parsed = _parse_experience_body(content)
    pub = _public_topic(
        {"filename": name, "title": meta.get("title") or "", "summary": meta.get("summary") or ""},
        path,
        content,
    )
    return {
        "filename": name,
        "title": meta.get("title") or parsed.get("title") or name[:-3],
        "summary": meta.get("summary") or parsed.get("summary") or "",
        "date": parsed.get("date") or "",
        "category": parsed.get("category") or "",
        "stocks": pub.get("stocks") or [],
        "sectors": pub.get("sectors") or [],
        "content": content,
        "body": parsed.get("body") or "",
        "path": path,
    }


def _tokens(text: str) -> list[str]:
    """简易中英关键词：连续中文按字 bigram，英文按词。"""
    s = (text or "").lower()
    out: list[str] = []
    for m in re.finditer(r"[a-z0-9_]+|[\u4e00-\u9fff]+", s):
        chunk = m.group(0)
        if re.fullmatch(r"[a-z0-9_]+", chunk):
            if len(chunk) >= 2:
                out.append(chunk)
            continue
        if len(chunk) == 1:
            out.append(chunk)
        else:
            out.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))
            out.extend(list(chunk))
    return out


def _score(query: str, *fields: str) -> float:
    q = _tokens(query)
    if not q:
        return 0.0
    blob = "\n".join(fields).lower()
    hit = 0.0
    for t in q:
        if t in blob:
            hit += 2.0 if len(t) >= 2 else 1.0
    # 完整子串加分
    raw_q = (query or "").strip().lower()
    if len(raw_q) >= 2 and raw_q in blob:
        hit += 5.0
    return hit


def retrieve(query: str, k: int = 3, root: Optional[str] = None) -> list[dict[str, Any]]:
    """按关键词从 index + 正文检索 Top-K 主题。"""
    k = max(1, min(int(k or 3), 10))
    q = (query or "").strip()
    if not q:
        return []
    base = ensure_dir(root)
    scored: list[tuple[float, dict[str, Any]]] = []
    for t in load_index_topics(base):
        path = os.path.join(base, t["filename"])
        content = _read_text(path) if os.path.isfile(path) else ""
        parsed = _parse_experience_body(content)
        stock_blob = " ".join(str(s.get("name") or "") for s in (parsed.get("stocks") or []))
        sector_blob = " ".join(str(s.get("name") or "") for s in (parsed.get("sectors") or []))
        sc = _score(
            q,
            t.get("title", ""),
            t.get("summary", ""),
            t["filename"],
            parsed.get("category") or "",
            parsed.get("date") or "",
            stock_blob,
            sector_blob,
            content[:8000],
        )
        if sc <= 0:
            continue
        scored.append((sc, {
            "filename": t["filename"],
            "title": t.get("title") or t["filename"][:-3],
            "summary": t.get("summary") or "",
            "date": parsed.get("date") or "",
            "category": parsed.get("category") or "",
            "stocks": parsed.get("stocks") or [],
            "sectors": parsed.get("sectors") or [],
            "content": content,
            "score": sc,
        }))
    scored.sort(key=lambda x: (-x[0], x[1]["filename"]))
    return [item for _, item in scored[:k]]


def format_context(hits: list[dict[str, Any]], limit_chars: int = 6000) -> str:
    """把检索结果拼成可注入 LLM 的上下文。"""
    if not hits:
        return ""
    parts = ["【经验记忆】以下为主题摘录，回答时优先参考，并注明依据主题名："]
    used = 0
    for h in hits:
        block = (
            f"\n### {h.get('title') or h['filename']}\n"
            f"文件：{h['filename']}\n"
            f"{(h.get('content') or h.get('summary') or '').strip()}\n"
        )
        if used + len(block) > limit_chars:
            remain = max(0, limit_chars - used - 80)
            if remain > 0:
                parts.append(block[:remain] + "\n…（截断）\n")
            break
        parts.append(block)
        used += len(block)
    return "".join(parts).strip()


def commit_files(
    files: list[dict[str, Any]],
    root: Optional[str] = None,
) -> dict[str, Any]:
    """确认写入主题文件并刷新 index.md；个股/板块经处理器解析。"""
    if not isinstance(files, list) or not files:
        raise ValueError("files 不能为空")
    base = ensure_dir(root)

    # 锁外解析个股/板块，避免持锁调用外部处理器
    prepared: list[dict[str, Any]] = []
    for raw in files:
        if not isinstance(raw, dict):
            raise ValueError("files 项必须是对象")
        date = normalize_date(str(raw.get("date") or ""))
        category = normalize_category(raw.get("category"))
        title_in = str(raw.get("title") or "").strip() or "未命名主题"
        title = suffix_title_date(title_in, date)
        filename = str(raw.get("filename") or "").strip()
        if not filename:
            filename = dated_filename(title, date)
        else:
            filename = sanitize_filename(filename)
        raw_content = str(raw.get("content") or "")
        body = _strip_body_wrapper(raw_content, title)
        if not body.strip():
            raise ValueError(f"主题内容不能为空：{filename}")
        summary = str(raw.get("summary") or "").strip()
        if not summary:
            for line in body.splitlines():
                s = line.strip().lstrip("#").strip()
                if s:
                    summary = s[:80]
                    break
            if not summary:
                summary = title
        stocks, sectors = resolve_experience_targets(
            text="\n".join(filter(None, [title, summary, body])),
            raw_stocks=raw.get("stocks") if isinstance(raw.get("stocks"), list) else [],
            raw_sectors=raw.get("sectors") if isinstance(raw.get("sectors"), list) else [],
            feed=True,
        )
        content = build_experience_markdown(
            title=title,
            date=date,
            category=category,
            summary=summary,
            body=body,
            stocks=stocks,
            sectors=sectors,
        )
        prepared.append({
            "filename": filename,
            "title": title,
            "summary": summary,
            "date": date,
            "category": category,
            "content": content,
            "stocks": stocks,
            "sectors": sectors,
        })

    written: list[dict[str, Any]] = []
    with _LOCK:
        topics = {t["filename"].lower(): dict(t) for t in load_index_topics(base)}
        for item in prepared:
            path = _topic_path(item["filename"], base)
            body = item["content"]
            _atomic_write_text(path, body if body.endswith("\n") else body + "\n")
            entry = {
                "filename": os.path.basename(path),
                "title": item["title"],
                "summary": item["summary"],
            }
            topics[entry["filename"].lower()] = entry
            written.append({
                **entry,
                "path": path,
                "date": item["date"],
                "category": item["category"],
                "stocks": item["stocks"],
                "sectors": item["sectors"],
            })

        ordered = sorted(topics.values(), key=lambda t: t["filename"])
        index_path = os.path.join(base, INDEX_NAME)
        _atomic_write_text(index_path, build_index(ordered, base))

    return {
        "ok": True,
        "root": base,
        "written": written,
        "topics": list_topics_for_api(base),
    }


def delete_topic(filename: str, root: Optional[str] = None) -> dict[str, Any]:
    """删除主题文件并刷新 index.md。"""
    path = _topic_path(filename, root)
    name = os.path.basename(path)
    base = ensure_dir(root)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"主题不存在：{name}")

    with _LOCK:
        try:
            os.unlink(path)
        except OSError as exc:
            raise OSError(f"删除主题失败：{name}") from exc
        topics = {t["filename"].lower(): dict(t) for t in load_index_topics(base)}
        topics.pop(name.lower(), None)
        ordered = sorted(topics.values(), key=lambda t: t["filename"])
        index_path = os.path.join(base, INDEX_NAME)
        _atomic_write_text(index_path, build_index(ordered, base))

    return {
        "ok": True,
        "root": base,
        "deleted": name,
        "topics": list_topics_for_api(base),
    }
