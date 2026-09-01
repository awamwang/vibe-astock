"""与 duanxian.paths 对齐的落盘根解析（不依赖 duanxian，便于整树拷贝）。

优先读环境变量（由 VIBE_PROFILE / set_profile 写入），否则回落到用户主目录。
"""

from __future__ import annotations

import os
from pathlib import Path


def profile_root() -> Path:
    raw = (os.environ.get("VIBE_PROFILE") or "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return Path.home()


def agents_dir() -> Path:
    raw = (os.environ.get("DUANXIAN_AGENTS_DIR") or "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return profile_root() / ".duanxian-agents"


def research_dir() -> Path:
    raw = (os.environ.get("VR_DATA_DIR") or "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return profile_root() / ".vibe-research"


def astock_dir() -> Path:
    raw = (os.environ.get("VIBE_ASTOCK_DIR") or "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return profile_root() / ".vibe-astock"
