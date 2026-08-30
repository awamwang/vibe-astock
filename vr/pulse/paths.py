"""预测市场快照与翻译缓存目录。"""
from __future__ import annotations

import os
from pathlib import Path


def get_pulse_data_dir() -> Path:
    """快照根目录：VR_DATA_DIR 或 ~/.vibe-research 下的 market_pulse/。"""
    root = Path(os.environ.get("VR_DATA_DIR") or (Path.home() / ".vibe-research"))
    path = root / "market_pulse"
    path.mkdir(parents=True, exist_ok=True)
    return path
