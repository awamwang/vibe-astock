"""跨节点共用的小工具。"""

from __future__ import annotations

from .roles import MACRO_FIELD, MACRO_TITLE, ROLES
from .state import DuanxianReviewState


def collect_reports(state: DuanxianReviewState) -> str:
    """把已产出的分析师报告拼成一段供裁判读取（角色顺序来自 registry + 大板块）。"""
    pairs = [(r.report_field, r.title) for r in ROLES] + [(MACRO_FIELD, MACRO_TITLE)]
    return _collect(state, pairs)


def collect_reports(state: dict, pairs) -> str:
    """把已产出的分析师报告拼成一段。pairs = [(state字段名, 展示标题), ...]，空的跳过。"""
    parts = []
    for field, label in pairs:
        v = (state.get(field) or "").strip()
        if v:
            parts.append(f"【{label}】\n{v}")
    return "\n\n".join(parts) if parts else "（暂无分析师报告）"
