"""研报文章库 —— 原文 Markdown + index.md，摘要索引，个股/板块经处理器解析。

落盘：`~/.duanxian-agents/articles/`
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
    DIR = str(_paths.agents_dir() / "articles")


INDEX_NAME = "index.md"
_LOCK = threading.Lock()

_RESERVED = frozenset({INDEX_NAME.lower(), "readme.md"})
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TOPIC_LINE = re.compile(
    r"^-\s+\*\*(?P<title>.+?)\*\*\s*[|｜]\s*`(?P<file>[^`]+)`\s*[—\-–]\s*(?P<summary>.*)\s*$"
)
_CODE_RE = re.compile(r"^\d{6}$")


def ensure_dir(root: Optional[str] = None) -> str:
    """确保文章库目录存在，返回绝对路径。"""
    path = os.path.abspath(root or DIR)
    os.makedirs(path, exist_ok=True)
    return path


def root_path(root: Optional[str] = None) -> str:
    return ensure_dir(root)


def sanitize_filename(name: str) -> str:
    """标题 → 安全的中文 `.md` 文件名。"""
    raw = (name or "").strip()
    if raw.lower().endswith(".md"):
        raw = raw[:-3].strip()
    raw = _BAD_CHARS.sub("", raw).replace("..", "").strip(" .")
    if not raw:
        raw = "未命名文章"
    filename = f"{raw}.md"
    if filename.lower() in _RESERVED:
        filename = f"{raw}-文章.md"
    return filename


def dated_filename(title: str, date: Optional[str] = None) -> str:
    """标题 + 日期 → 文件名（如 `白酒景气-2026-08-28.md`）。"""
    day = (date or "").strip() or china_today()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        day = china_today()
    base = (title or "").strip() or "未命名文章"
    if base.lower().endswith(".md"):
        base = base[:-3].strip()
    # 已带同日后缀则不再重复拼接
    if re.search(rf"-{re.escape(day)}$", base):
        return sanitize_filename(base)
    return sanitize_filename(f"{base}-{day}")


def _article_path(filename: str, root: Optional[str] = None) -> str:
    base = ensure_dir(root)
    name = os.path.basename(filename.strip())
    if not name.lower().endswith(".md"):
        name = f"{name}.md"
    if name.lower() in _RESERVED:
        raise ValueError(f"保留文件名不可用作文章：{name}")
    if _BAD_CHARS.search(name[:-3]) or ".." in name:
        raise ValueError(f"非法文章文件名：{name}")
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
    """解析 index.md 文章列表。"""
    articles: list[dict[str, str]] = []
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
        articles.append({
            "filename": filename,
            "title": m.group("title").strip() or filename[:-3],
            "summary": m.group("summary").strip(),
        })
    return articles


def build_index(articles: list[dict[str, str]], root: Optional[str] = None) -> str:
    """生成 index.md 全文。"""
    base = root_path(root)
    lines = [
        "# 研报文章索引",
        "",
        f"> 库根路径：`{base}`",
        "> 供外部 Agent / 本应用问答检索。确认写入后自动更新。",
        "",
        f"_更新于 {china_now().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        "## 文章",
        "",
    ]
    if not articles:
        lines.append("_（暂无文章）_")
    else:
        for a in articles:
            title = (a.get("title") or "").strip() or a["filename"][:-3]
            summary = (a.get("summary") or "").strip() or "（无摘要）"
            lines.append(f"- **{title}** | `{a['filename']}` — {summary}")
    lines.append("")
    return "\n".join(lines)


def list_article_files(root: Optional[str] = None) -> list[str]:
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


def load_index_articles(root: Optional[str] = None) -> list[dict[str, str]]:
    """读 index；若缺失则按目录扫描补齐。"""
    base = ensure_dir(root)
    index_path = os.path.join(base, INDEX_NAME)
    articles = parse_index(_read_text(index_path))
    by_name = {a["filename"].lower(): a for a in articles}
    for name in list_article_files(base):
        if name.lower() in by_name:
            continue
        articles.append({"filename": name, "title": name[:-3], "summary": ""})
    return articles


def get_meta(root: Optional[str] = None) -> dict[str, Any]:
    base = root_path(root)
    articles = load_index_articles(base)
    return {
        "root": base,
        "index_path": os.path.join(base, INDEX_NAME),
        "articles": articles,
    }


def read_article(filename: str, root: Optional[str] = None) -> dict[str, Any]:
    path = _article_path(filename, root)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"文章不存在：{os.path.basename(path)}")
    name = os.path.basename(path)
    articles = {a["filename"].lower(): a for a in load_index_articles(root)}
    meta = articles.get(name.lower(), {})
    content = _read_text(path)
    parsed = _parse_article_body(content)
    return {
        "filename": name,
        "title": meta.get("title") or parsed.get("title") or name[:-3],
        "summary": meta.get("summary") or parsed.get("summary") or "",
        "date": parsed.get("date") or "",
        "stocks": parsed.get("stocks") or [],
        "sectors": parsed.get("sectors") or [],
        "content": content,
        "original": extract_original(content),
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
    raw_q = (query or "").strip().lower()
    if len(raw_q) >= 2 and raw_q in blob:
        hit += 5.0
    return hit


def retrieve(query: str, k: int = 3, root: Optional[str] = None) -> list[dict[str, Any]]:
    """按关键词从 index + 正文检索 Top-K 文章。"""
    k = max(1, min(int(k or 3), 10))
    q = (query or "").strip()
    if not q:
        return []
    base = ensure_dir(root)
    scored: list[tuple[float, dict[str, Any]]] = []
    for a in load_index_articles(base):
        path = os.path.join(base, a["filename"])
        content = _read_text(path) if os.path.isfile(path) else ""
        sc = _score(q, a.get("title", ""), a.get("summary", ""), a["filename"], content[:8000])
        if sc <= 0:
            continue
        scored.append((sc, {
            "filename": a["filename"],
            "title": a.get("title") or a["filename"][:-3],
            "summary": a.get("summary") or "",
            "content": content,
            "score": sc,
        }))
    scored.sort(key=lambda x: (-x[0], x[1]["filename"]))
    return [item for _, item in scored[:k]]


def format_context(hits: list[dict[str, Any]], limit_chars: int = 6000) -> str:
    """把检索结果拼成可注入 LLM 的上下文。"""
    if not hits:
        return ""
    parts = ["【研报文章】以下为文章摘录，回答时优先参考，并注明依据标题："]
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


def _norm_stock_query(row: Any) -> dict[str, Optional[str]] | None:
    if not isinstance(row, dict):
        raw = str(row or "").strip()
        if not raw:
            return None
        if _CODE_RE.match(raw):
            return {"code": raw, "name": None}
        return {"code": None, "name": raw}
    code = str(row.get("code") or "").strip()
    name = str(row.get("name") or "").strip()
    if code and not _CODE_RE.match(code):
        # 名称误放在 code 时挪到 name
        if not name:
            name = code
        code = ""
    if not code and not name:
        return None
    return {"code": code or None, "name": name or None}


def _resolve_stocks(raw_stocks: list[Any]) -> list[dict[str, Any]]:
    """经个股处理器解析文中个股。"""
    queries: list[dict[str, Any]] = []
    for row in raw_stocks or []:
        q = _norm_stock_query(row)
        if q:
            queries.append(q)
    if not queries:
        return []
    try:
        from duanxian import vr_host as vh

        vh._add_vr_to_path()
        import stock_processor  # noqa: PLC0415

        return stock_processor.resolve_many(queries)
    except Exception:  # noqa: BLE001
        # 处理器不可用时保留原始候选，不阻断落盘
        out: list[dict[str, Any]] = []
        for q in queries:
            out.append({
                "key": "",
                "code": q.get("code"),
                "name": q.get("name"),
                "status": "unmatched",
                "stock": None,
            })
        return out


def _resolve_sectors(raw_sectors: list[Any]) -> list[dict[str, Any]]:
    """经板块处理器解析文中板块，并喂入待匹配列表。"""
    names: list[str] = []
    seen: set[str] = set()
    for row in raw_sectors or []:
        if isinstance(row, dict):
            name = str(row.get("name") or row.get("raw") or "").strip()
        else:
            name = str(row or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    if not names:
        return []
    try:
        from duanxian import vr_host as vh

        vh._add_vr_to_path()
        from ths_block import processor as block_processor  # noqa: PLC0415

        results = block_processor.resolve_many(names)
        # 喂入文章来源，便于未匹配项进入待处理队列
        try:
            block_processor.feed("article", names)
        except Exception:  # noqa: BLE001
            pass
        return results
    except Exception:  # noqa: BLE001
        return [
            {
                "raw": n,
                "mapped": n,
                "status": "unmatched",
                "block": None,
                "candidates": [],
            }
            for n in names
        ]


def _format_stocks_line(stocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for s in stocks:
        stock = s.get("stock") if isinstance(s.get("stock"), dict) else None
        if stock:
            code = str(stock.get("code") or "").strip()
            name = str(stock.get("name") or "").strip()
            label = f"{code} {name}".strip() if code or name else ""
        else:
            code = str(s.get("code") or "").strip()
            name = str(s.get("name") or "").strip()
            label = f"{code} {name}".strip() if code or name else ""
            if label and s.get("status") == "unmatched":
                label = f"{label}（未匹配）"
        if label:
            parts.append(label)
    return "；".join(parts) if parts else "（无）"


def _format_sectors_line(sectors: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for s in sectors:
        block = s.get("block") if isinstance(s.get("block"), dict) else None
        if block:
            name = str(block.get("name") or "").strip()
            kind = str(block.get("kind_label") or block.get("kind") or "").strip()
            label = f"{name}（{kind}）" if name and kind else name
        else:
            name = str(s.get("mapped") or s.get("raw") or s.get("name") or "").strip()
            label = f"{name}（未匹配）" if name and s.get("status") != "matched" else name
        if label:
            parts.append(label)
    return "；".join(parts) if parts else "（无）"


# 明显与正文无关的 UI / 营销 / 粘贴杂质（整行匹配，保守删除）
_NOISE_LINE = re.compile(
    r"^\s*(?:"
    r"打开微信扫一扫|"
    r"扫码关注(?:公众号)?|"
    r"长按识别二维码|"
    r"关注公众号|"
    r"点击阅读原文|"
    r"阅读原文|"
    r"展开全文|"
    r"收起全文|"
    r"复制全文|"
    r"分享到(?:微信|朋友圈|微博|QQ)?|"
    r"点赞|在看|收藏|转发|"
    r"相关推荐|猜你喜欢|热门评论|热门文章|"
    r"登录后查看(?:全文|更多)?|"
    r"下载.+?(?:APP|客户端|应用)|"
    r"打开APP|"
    r"广告|"
    r"Cookie\s*(?:设置|政策|同意)?|"
    r"我们使用\s*Cookie|"
    r"本网站使用Cookie|"
    r")\s*[。.!！]?$",
    re.I,
)
# 单独成行的页码 / 装饰分隔（不含 markdown 的 ---）
_PAGE_ONLY = re.compile(
    r"^\s*(?:"
    r"[—\-–~～·•]*\s*\d{1,4}\s*[—\-–~～·•]*|"
    r"第\s*\d{1,4}\s*页|"
    r"Page\s*\d{1,4}|"
    r"[=\-*_]{4,}|"
    r"[·•…]{3,}"
    r")\s*$",
    re.I,
)
_ZW_CHARS = re.compile(r"[\u200b\u200c\u200d\ufeff\u00ad]")
_MULTI_SPACE = re.compile(r"[^\S\n]{2,}")
_MULTI_BLANK = re.compile(r"\n{3,}")


def _is_noise_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if _NOISE_LINE.match(s):
        return True
    if _PAGE_ONLY.match(s):
        return True
    # 极短且全是符号/空白的装饰行
    if len(s) <= 2 and not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", s):
        return True
    return False


def clean_original_text(text: str) -> str:
    """轻度清洗粘贴原文：去明显杂质、整理空白，最大限度保留正文。

    不做语义改写、不删段落级正文内容。
    """
    if not text:
        return ""
    s = str(text).replace("\r\n", "\n").replace("\r", "\n")
    s = _ZW_CHARS.sub("", s)
    # 全角空格统一，便于后续压缩
    s = s.replace("\u3000", " ")

    kept: list[str] = []
    for raw_line in s.split("\n"):
        line = raw_line.rstrip()
        # 行内多余空格压缩（保留单个空格；中文不受影响）
        line = _MULTI_SPACE.sub(" ", line)
        if _is_noise_line(line):
            continue
        kept.append(line)

    out = "\n".join(kept)
    out = _MULTI_BLANK.sub("\n\n", out)
    return out.strip()


def build_article_markdown(
    *,
    title: str,
    date: str,
    summary: str,
    original: str,
    stocks: list[dict[str, Any]],
    sectors: list[dict[str, Any]],
) -> str:
    """组装落盘 Markdown：元数据 + 清洗后的原文。"""
    body = clean_original_text(original)
    lines = [
        f"# {title}",
        "",
        f"- 日期：{date}",
        f"- 摘要：{summary}",
        f"- 个股：{_format_stocks_line(stocks)}",
        f"- 板块：{_format_sectors_line(sectors)}",
        "",
        "## 原文",
        "",
        body,
        "",
    ]
    return "\n".join(lines)


def _parse_meta_list(line: str, prefix: str) -> list[str]:
    raw = line[len(prefix):].strip()
    if not raw or raw == "（无）":
        return []
    parts = re.split(r"[；;、,，]", raw)
    out: list[str] = []
    for p in parts:
        s = p.strip()
        if s:
            out.append(s)
    return out


def _parse_article_body(content: str) -> dict[str, Any]:
    """从已落盘正文反解元数据（尽力而为）。"""
    title = ""
    date = ""
    summary = ""
    stock_labels: list[str] = []
    sector_labels: list[str] = []
    lines = (content or "").splitlines()
    for line in lines[:40]:
        s = line.strip()
        if s.startswith("# ") and not title:
            title = s[2:].strip()
            continue
        if s.startswith("- 日期："):
            date = s[5:].strip()
        elif s.startswith("- 摘要："):
            summary = s[5:].strip()
        elif s.startswith("- 个股："):
            stock_labels = _parse_meta_list(s, "- 个股：")
        elif s.startswith("- 板块："):
            sector_labels = _parse_meta_list(s, "- 板块：")
    stocks = [{"name": x, "code": None, "status": "label"} for x in stock_labels]
    sectors = [{"name": x, "status": "label"} for x in sector_labels]
    return {
        "title": title,
        "date": date,
        "summary": summary,
        "stocks": stocks,
        "sectors": sectors,
    }


def extract_original(content: str) -> str:
    """从落盘 Markdown 取出「## 原文」之后的正文；无标记时退回全文。"""
    text = content or ""
    marker = "## 原文"
    idx = text.find(marker)
    if idx < 0:
        return text.strip()
    body = text[idx + len(marker):].lstrip("\r\n")
    return body.strip()


def _targets_from_article(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """把文章元数据里的个股/板块标签转成消息标的。"""
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(kind: str, code: str | None, name: str) -> None:
        name = (name or "").strip()
        code = (code or "").strip() or None
        if not name and not code:
            return
        key = (kind, code or "", name)
        if key in seen:
            return
        seen.add(key)
        targets.append({"kind": kind, "code": code, "name": name or code or ""})

    for row in parsed.get("stocks") or []:
        label = str((row or {}).get("name") or "").strip()
        if not label:
            continue
        label = re.sub(r"（未匹配）|\(未匹配\)$", "", label).strip()
        m = re.match(r"^(\d{6})\s+(.+)$", label)
        if m:
            _add("stock", m.group(1), m.group(2).strip())
        elif _CODE_RE.match(label):
            _add("stock", label, label)
        else:
            _add("stock", None, label)

    for row in parsed.get("sectors") or []:
        label = str((row or {}).get("name") or "").strip()
        if not label:
            continue
        label = re.sub(r"（未匹配）|\(未匹配\)$", "", label).strip()
        # 「白酒（概念）」→ 白酒
        label = re.sub(r"（[^）]+）|\([^)]+\)$", "", label).strip() or label
        if label:
            _add("sector", None, label)
    return targets


def build_message_draft(filename: str, root: Optional[str] = None) -> dict[str, Any]:
    """把研报文章转成消息录入草稿（产生时间=转换时刻，原文末尾保留文件关联）。"""
    art = read_article(filename, root)
    name = art["filename"]
    path = art["path"]
    original = extract_original(art["content"])
    if not original.strip():
        raise ValueError(f"文章原文为空，无法转为消息：{name}")

    link_block = (
        f"\n\n---\n"
        f"关联研报文章文件：`{name}`\n"
        f"路径：`{path}`\n"
    )
    # 避免重复追加关联块
    if f"关联研报文章文件：`{name}`" in original:
        content = original if original.endswith("\n") else original + "\n"
    else:
        content = original.rstrip() + link_block

    produced_at = china_now().strftime("%Y-%m-%d %H:%M:%S")
    parsed = {
        "stocks": art.get("stocks") or [],
        "sectors": art.get("sectors") or [],
    }
    targets = _targets_from_article(parsed)
    summary = (art.get("summary") or "").strip() or art.get("title") or name
    draft = {
        "draft_key": f"article-to-msg-{name}-{int(china_now().timestamp())}",
        "source_id": "article",
        "source_label": "研报文章",
        "content": content,
        "title": art.get("title") or name[:-3],
        "keywords": [],
        "url": "",
        "marks": [],
        "produced_at": produced_at,
        "targets": targets,
        "meta": {
            "format": "article",
            "from_article": True,
            "article_filename": name,
            "article_path": path,
            "summary": summary,
            "article_date": art.get("date") or "",
        },
    }
    return {"draft": draft, "article": art, "produced_at": produced_at}


def to_message(filename: str, root: Optional[str] = None) -> dict[str, Any]:
    """将文章插入消息分析库，返回入库结果。"""
    built = build_message_draft(filename, root)
    draft_dict = built["draft"]

    from duanxian import vr_host as vh

    vh._add_vr_to_path()
    from message.schemas import RawMessageDraft  # noqa: PLC0415
    from message import store as msg_store  # noqa: PLC0415

    draft = RawMessageDraft.model_validate(draft_dict)
    inserted = msg_store.insert_raw_batch([draft])
    if not inserted:
        raise ValueError("消息入库未写入（可能与已有内容重复）")

    analyzed = []
    for raw in inserted:
        patch: dict[str, Any] = {
            "title": draft.title,
            "detail": draft.content,
            "summary": str((draft.meta or {}).get("summary") or draft.title),
        }
        if draft.targets:
            patch["targets"] = [t.model_dump() for t in draft.targets]
        if draft.keywords:
            patch["keywords"] = list(draft.keywords)
        analyzed.append(msg_store.upsert_analyzed_from_raw(raw, patch=patch, analyzed_by="rule"))

    return {
        "ok": True,
        "produced_at": built["produced_at"],
        "article_filename": built["article"]["filename"],
        "article_path": built["article"]["path"],
        "inserted": [r.model_dump() for r in inserted],
        "analyzed": [a.model_dump() for a in analyzed],
    }


def commit_files(
    files: list[dict[str, Any]],
    root: Optional[str] = None,
) -> dict[str, Any]:
    """确认写入文章文件并刷新 index.md；个股/板块经处理器解析。"""
    if not isinstance(files, list) or not files:
        raise ValueError("files 不能为空")
    base = ensure_dir(root)

    # 锁外解析个股/板块，避免持锁调用外部处理器
    prepared: list[dict[str, Any]] = []
    for raw in files:
        if not isinstance(raw, dict):
            raise ValueError("files 项必须是对象")
        title = str(raw.get("title") or "").strip() or "未命名文章"
        date = str(raw.get("date") or "").strip() or china_today()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            date = china_today()
        filename = str(raw.get("filename") or "").strip()
        if not filename:
            filename = dated_filename(title, date)
        else:
            filename = sanitize_filename(filename)
        # 用户原文优先；缺省时再用 content；落盘前轻度清洗
        original = clean_original_text(str(raw.get("original") or raw.get("content") or ""))
        if not original.strip():
            raise ValueError(f"文章原文不能为空：{filename}")
        summary = str(raw.get("summary") or "").strip()
        if not summary:
            for line in original.splitlines():
                s = line.strip().lstrip("#").strip()
                if s:
                    summary = s[:80]
                    break
            if not summary:
                summary = title
        stocks = _resolve_stocks(raw.get("stocks") if isinstance(raw.get("stocks"), list) else [])
        sectors = _resolve_sectors(raw.get("sectors") if isinstance(raw.get("sectors"), list) else [])
        content = build_article_markdown(
            title=title,
            date=date,
            summary=summary,
            original=original,
            stocks=stocks,
            sectors=sectors,
        )
        prepared.append({
            "filename": filename,
            "title": title,
            "summary": summary,
            "date": date,
            "content": content,
            "stocks": stocks,
            "sectors": sectors,
        })

    written: list[dict[str, Any]] = []
    with _LOCK:
        articles = {a["filename"].lower(): dict(a) for a in load_index_articles(base)}
        for item in prepared:
            path = _article_path(item["filename"], base)
            body = item["content"]
            _atomic_write_text(path, body if body.endswith("\n") else body + "\n")
            entry = {
                "filename": os.path.basename(path),
                "title": item["title"],
                "summary": item["summary"],
            }
            articles[entry["filename"].lower()] = entry
            written.append({
                **entry,
                "path": path,
                "date": item["date"],
                "stocks": item["stocks"],
                "sectors": item["sectors"],
            })

        ordered = sorted(articles.values(), key=lambda t: t["filename"])
        index_path = os.path.join(base, INDEX_NAME)
        _atomic_write_text(index_path, build_index(ordered, base))

    return {
        "ok": True,
        "root": base,
        "written": written,
        "articles": load_index_articles(base),
    }


def update_article(
    filename: str,
    *,
    content: Optional[str] = None,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    root: Optional[str] = None,
) -> dict[str, Any]:
    """更新已落盘文章全文（及索引标题/摘要）。文件名不变。"""
    path = _article_path(filename, root)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"文章不存在：{os.path.basename(path)}")
    name = os.path.basename(path)
    base = ensure_dir(root)

    old = _read_text(path)
    if content is None:
        new_content = old
    else:
        new_content = str(content)
        if not new_content.strip():
            raise ValueError("文章内容不能为空")
        # 若含「## 原文」块，仅对该块做轻度清洗，元数据区保持用户编辑结果
        marker = "## 原文"
        idx = new_content.find(marker)
        if idx >= 0:
            head = new_content[: idx + len(marker)]
            body = new_content[idx + len(marker):].lstrip("\r\n")
            cleaned = clean_original_text(body)
            new_content = head + "\n\n" + cleaned + ("\n" if cleaned else "")
        else:
            new_content = clean_original_text(new_content)

    parsed = _parse_article_body(new_content)
    new_title = (title if title is not None else "").strip() or parsed.get("title") or name[:-3]
    new_summary = (summary if summary is not None else "").strip() or parsed.get("summary") or new_title

    # 同步文首标题与摘要行（若结构仍是标准模板）
    lines = new_content.splitlines()
    if lines and lines[0].startswith("# "):
        lines[0] = f"# {new_title}"
    for i, line in enumerate(lines[:20]):
        if line.startswith("- 摘要："):
            lines[i] = f"- 摘要：{new_summary}"
            break
    new_content = "\n".join(lines)
    if not new_content.endswith("\n"):
        new_content += "\n"

    with _LOCK:
        _atomic_write_text(path, new_content)
        articles = {a["filename"].lower(): dict(a) for a in load_index_articles(base)}
        articles[name.lower()] = {
            "filename": name,
            "title": new_title,
            "summary": new_summary,
        }
        ordered = sorted(articles.values(), key=lambda t: t["filename"])
        index_path = os.path.join(base, INDEX_NAME)
        _atomic_write_text(index_path, build_index(ordered, base))

    return {
        "ok": True,
        "root": base,
        "article": read_article(name, base),
        "articles": load_index_articles(base),
    }
