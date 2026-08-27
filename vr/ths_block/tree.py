"""从 block_tree.ini 本地解析概念 / 行业 / 地域层级树。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_BLOCK_TREE_ROOT_SECTION = "BLOCK_TREE_ROOT"
_INI_SECTION_RE = re.compile(r"^\[([^\]]+)\]")
_STOCKBLOCK_REL = Path("xiadan-plus") / "quote" / "config" / "quota" / "stockblock"

_TREE_ROOT_IDS = {
    "conception": "2B",
    "industry": "DFF8",
    "region": "47",
}
_TREE_KIND_LABELS = {
    "conception": "概念",
    "industry": "行业",
    "region": "地域",
}


def _read_gbk(path: Path) -> str:
    return path.read_bytes().decode("gbk", errors="replace")


def _resolve_block_tree_ini(ths_dir: Path) -> Path:
    """优先 BlockUpdate/block_tree.ini，回退 stockblock/block_tree.ini。"""
    root = ths_dir.resolve()
    primary = root / "BlockUpdate" / "block_tree.ini"
    if primary.is_file():
        return primary
    fallback = root / _STOCKBLOCK_REL / "block_tree.ini"
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(f"未找到板块树配置: {primary} 或 {fallback}")


def parse_block_tree_sections(text: str) -> dict[str, list[tuple[str, str]]]:
    """解析 block_tree.ini 为节名 → [(键, 值), ...]。"""
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


def _find_root_section_ref(
    root_id: str,
    sections: dict[str, list[tuple[str, str]]],
) -> str:
    """查找 kind 根节点对应的 @节 引用（兼容 BLOCK_TREE_ROOT 嵌套总树）。"""
    root_map = dict(sections.get(_BLOCK_TREE_ROOT_SECTION, []))
    direct = root_map.get(root_id, "")
    if direct.startswith("@"):
        return direct

    visited: set[str] = set()
    queue: list[str] = []
    for value in root_map.values():
        if value.startswith("@"):
            queue.append(value)

    while queue:
        section = queue.pop(0)
        if section in visited:
            continue
        visited.add(section)
        for key, value in sections.get(section, []):
            if key == root_id and value.startswith("@"):
                return value
            if value.startswith("@"):
                queue.append(value)
    return ""


def _build_tree_nodes(
    section_name: str,
    sections: dict[str, list[tuple[str, str]]],
    names: dict[str, str],
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for block_id, value in sections.get(section_name, []):
        name = names.get(block_id, "")
        if value.startswith("@"):
            children = _build_tree_nodes(value, sections, names)
            nodes.append(
                {
                    "id": block_id,
                    "name": name,
                    "node_type": "branch",
                    "children": children,
                }
            )
        else:
            nodes.append(
                {
                    "id": block_id,
                    "name": name,
                    "node_type": "leaf",
                }
            )
    return nodes


def _count_tree_nodes(node: dict[str, Any]) -> tuple[int, int]:
    node_type = node.get("node_type")
    if node_type == "leaf":
        return 0, 1
    branch = 1
    leaf = 0
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        sub_branch, sub_leaf = _count_tree_nodes(child)
        branch += sub_branch
        leaf += sub_leaf
    return branch, leaf


def build_block_tree(
    ths_dir: str | Path,
    kind: str,
    *,
    names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """构建指定 kind 的板块层级树。"""
    kind_norm = kind.strip()
    root_id = _TREE_ROOT_IDS.get(kind_norm)
    if not root_id:
        raise ValueError(f"kind '{kind_norm}' 不支持 tree")

    root = Path(ths_dir).resolve()
    tree_path = _resolve_block_tree_ini(root)
    sections = parse_block_tree_sections(_read_gbk(tree_path))

    section_ref = _find_root_section_ref(root_id, sections)
    if not section_ref.startswith("@"):
        raise RuntimeError(
            f"板块树缺少 {kind_norm} 根节点 {root_id} 的子树引用: {tree_path}"
        )

    name_map = dict(names or {})
    root_name = name_map.get(root_id) or _TREE_KIND_LABELS.get(kind_norm, kind_norm)
    tree: dict[str, Any] = {
        "id": root_id,
        "name": root_name,
        "node_type": "branch",
        "children": _build_tree_nodes(section_ref, sections, name_map),
    }
    branch_count, leaf_count = _count_tree_nodes(tree)
    return {
        "kind": kind_norm,
        "kind_label": _TREE_KIND_LABELS.get(kind_norm, kind_norm),
        "root_id": root_id,
        "root_name": root_name,
        "tree": tree,
        "branch_count": branch_count,
        "leaf_count": leaf_count,
    }
