"""预测市场快照与翻译缓存目录。"""
from __future__ import annotations

from pathlib import Path

from profile_paths import research_dir


def get_pulse_data_dir() -> Path:
    """快照根目录：VR_DATA_DIR / profile 下 .vibe-research 的 market_pulse/。"""
    path = research_dir() / "market_pulse"
    path.mkdir(parents=True, exist_ok=True)
    return path
