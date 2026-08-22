"""交易经验记忆库 —— 主题 Markdown + index.md，供本页问答 / 全局问 AI / 外部 Agent 调取。

落盘：`~/.duanxian-agents/experience/`
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any, Optional

from .util import china_now, safe_join

DIR = os.path.expanduser("~/.duanxian-agents/experience")
INDEX_NAME = "index.md"
_LOCK = threading.Lock()

_RESERVED = frozenset({INDEX_NAME.lower(), "readme.md"})
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TOPIC_LINE = re.compile(
    r"^-\s+\*\*(?P<title>.+?)\*\*\s*[|｜]\s*`(?P<file>[^`]+)`\s*[—\-–]\s*(?P<summary>.*)\s*$"
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


def get_meta(root: Optional[str] = None) -> dict[str, Any]:
    base = root_path(root)
    topics = load_index_topics(base)
    return {
        "root": base,
        "index_path": os.path.join(base, INDEX_NAME),
        "topics": topics,
    }


def read_topic(filename: str, root: Optional[str] = None) -> dict[str, str]:
    path = _topic_path(filename, root)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"主题不存在：{os.path.basename(path)}")
    name = os.path.basename(path)
    topics = {t["filename"].lower(): t for t in load_index_topics(root)}
    meta = topics.get(name.lower(), {})
    return {
        "filename": name,
        "title": meta.get("title") or name[:-3],
        "summary": meta.get("summary") or "",
        "content": _read_text(path),
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
        sc = _score(q, t.get("title", ""), t.get("summary", ""), t["filename"], content[:8000])
        if sc <= 0:
            continue
        scored.append((sc, {
            "filename": t["filename"],
            "title": t.get("title") or t["filename"][:-3],
            "summary": t.get("summary") or "",
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
    """确认写入主题文件并刷新 index.md。"""
    if not isinstance(files, list) or not files:
        raise ValueError("files 不能为空")
    base = ensure_dir(root)
    written: list[dict[str, str]] = []
    with _LOCK:
        topics = {t["filename"].lower(): dict(t) for t in load_index_topics(base)}
        for raw in files:
            if not isinstance(raw, dict):
                raise ValueError("files 项必须是对象")
            title = str(raw.get("title") or "").strip()
            filename = str(raw.get("filename") or "").strip()
            if not filename:
                filename = sanitize_filename(title or "未命名主题")
            else:
                filename = sanitize_filename(filename)
            content = str(raw.get("content") or "")
            if not content.strip():
                raise ValueError(f"主题内容不能为空：{filename}")
            summary = str(raw.get("summary") or "").strip()
            if not summary:
                # 取正文首行非空作摘要
                for line in content.splitlines():
                    s = line.strip().lstrip("#").strip()
                    if s:
                        summary = s[:80]
                        break
            if not title:
                title = filename[:-3]
            path = _topic_path(filename, base)
            _atomic_write_text(path, content if content.endswith("\n") else content + "\n")
            entry = {"filename": os.path.basename(path), "title": title, "summary": summary}
            topics[entry["filename"].lower()] = entry
            written.append({**entry, "path": path})

        ordered = sorted(topics.values(), key=lambda t: t["filename"])
        index_path = os.path.join(base, INDEX_NAME)
        _atomic_write_text(index_path, build_index(ordered, base))

    return {
        "ok": True,
        "root": base,
        "written": written,
        "topics": load_index_topics(base),
    }
