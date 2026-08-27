"""从同花顺本地文件解析板块成分股。"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

_INI_SECTION_RE = re.compile(r"^\[([^\]]+)\]")
_CODE_RE = re.compile(r"^\d{6}$")
_THS_BLOCK_FILE_RE = re.compile(r"^\d+$")

# kind → stockblock 下 INI 文件名（与 ths-linker 一致）
_SYSTEM_BLOCK_FILES: dict[str, list[str]] = {
    "conception": ["block_conception.ini"],
    "industry": ["block_industry.ini", "block_industry3.ini"],
    "region": ["block_region.ini"],
    "daily": ["block_every_day.ini"],
}

_STOCKBLOCK_REL = Path("xiadan-plus") / "quote" / "config" / "quota" / "stockblock"
_CUSTOM_BLOCK_DIR = "custom_block"
_USERS_INI = "users.ini"
_USERS_INI_LAST_ID_RE = re.compile(r"last_userid\s*=\s*(\S+)", re.IGNORECASE)
_USERS_INI_USER_LINE_RE = re.compile(r"^(\d+)\s*=\s*([^,]+),\s*(\S+)", re.MULTILINE)


def _read_gbk(path: Path) -> str:
    return path.read_bytes().decode("gbk", errors="replace")


def _parse_ini_sections(text: str) -> dict[str, list[tuple[str, str]]]:
    sections: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        sec_match = _INI_SECTION_RE.match(line)
        if sec_match:
            current = sec_match.group(1)
            sections.setdefault(current, [])
            continue
        if current is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        sections[current].append((key.strip(), value.strip()))
    return sections


def _stockblock_dir(ths_dir: Path) -> Path:
    path = ths_dir / _STOCKBLOCK_REL
    if not path.is_dir():
        raise FileNotFoundError(f"未找到同花顺板块配置目录: {path}")
    return path


def _parse_stock_context_value(raw: str) -> list[dict[str, str]]:
    """解析 ``17:600519,33:000001`` 或 custom ``603186|603366|`` 格式。"""
    text = (raw or "").strip()
    if not text:
        return []
    if "|" in text:
        codes: list[dict[str, str]] = []
        seen: set[str] = set()
        for part in text.split("|"):
            code = part.strip().rstrip(",")
            if _CODE_RE.match(code) and code not in seen:
                seen.add(code)
                codes.append({"code": code, "market": ""})
        return codes
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in text.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        market, _, code = item.partition(":")
        code = code.strip()
        if not _CODE_RE.match(code) or code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "market": market.strip()})
    return out


def _load_system_stock_context(ths_dir: Path, kind: str) -> dict[str, str]:
    """读取系统板块 INI 的 BLOCK_STOCK_CONTEXT 节，合并多文件。"""
    names = _SYSTEM_BLOCK_FILES.get(kind)
    if not names:
        return {}
    base = _stockblock_dir(ths_dir)
    merged: dict[str, str] = {}
    for name in names:
        path = base / name
        if not path.is_file():
            raise FileNotFoundError(f"未找到板块配置文件: {path}")
        sections = _parse_ini_sections(_read_gbk(path))
        for block_id, value in sections.get("BLOCK_STOCK_CONTEXT", []):
            if value and "|" not in value and ":" in value:
                merged[block_id] = value
            elif value and "|" in value:
                merged[block_id] = value
            elif value:
                merged[block_id] = value
    return merged


def _parse_users_ini(ths_dir: Path) -> tuple[str | None, dict[str, tuple[str, str]]]:
    users_ini = ths_dir / _USERS_INI
    if not users_ini.is_file():
        raise FileNotFoundError(f"未找到 users.ini: {users_ini}")
    text = users_ini.read_bytes().decode("gbk", errors="replace")
    last_id: str | None = None
    match = _USERS_INI_LAST_ID_RE.search(text)
    if match:
        last_id = match.group(1).strip()
    users: dict[str, tuple[str, str]] = {}
    for m in _USERS_INI_USER_LINE_RE.finditer(text):
        uid, name, path_name = m.group(1), m.group(2).strip(), m.group(3).strip()
        if path_name:
            users[uid] = (name, path_name)
    return last_id, users


def _resolve_custom_block_dir(ths_dir: Path) -> Path:
    ths_dir = ths_dir.resolve()
    last_id, users = _parse_users_ini(ths_dir)
    candidates: list[Path] = []
    if last_id and last_id in users:
        cand = ths_dir / users[last_id][1] / _CUSTOM_BLOCK_DIR
        if cand.is_dir():
            return cand
        candidates.append(cand)
    found: list[Path] = []
    for child in ths_dir.iterdir():
        if not child.is_dir():
            continue
        cb = child / _CUSTOM_BLOCK_DIR
        if cb.is_dir() and "guest" not in child.name.lower():
            found.append(cb)
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        found.sort(
            key=lambda cb: max(
                (f.stat().st_mtime for f in cb.iterdir() if f.is_file() and _THS_BLOCK_FILE_RE.fullmatch(f.name)),
                default=0.0,
            ),
            reverse=True,
        )
        return found[0]
    if candidates:
        raise FileNotFoundError(f"未找到自定义板块目录: {candidates[0]}")
    raise FileNotFoundError(f"未找到自定义板块目录: {ths_dir}/<用户目录>/{_CUSTOM_BLOCK_DIR}")


def _load_custom_block_context(ths_dir: Path, block_id: str) -> str:
    block_dir = _resolve_custom_block_dir(ths_dir)
    path = block_dir / block_id
    if not path.is_file():
        raise FileNotFoundError(f"未找到自定义板块文件: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return ""
    return str(data.get("context") or "")


def list_block_stocks(ths_dir: Path, *, kind: str, block_id: str) -> list[dict[str, str]]:
    """返回板块成分股列表。"""
    root = Path(ths_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"同花顺目录不存在: {root}")
    block_id = str(block_id or "").strip()
    if not block_id:
        raise ValueError("缺少 block_id")

    if kind == "custom":
        raw = _load_custom_block_context(root, block_id)
        return _parse_stock_context_value(raw)

    ctx_map = _load_system_stock_context(root, kind)
    raw = ctx_map.get(block_id, "")
    return _parse_stock_context_value(raw)


def count_block_stocks(ths_dir: Path, *, kind: str, block_id: str) -> int:
    return len(list_block_stocks(ths_dir, kind=kind, block_id=block_id))
