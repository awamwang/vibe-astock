"""scripts/release.py 单元测试（不依赖真实 git 写操作）。"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release.py"


def _load_release():
    spec = importlib.util.spec_from_file_location("release_tool", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # dataclasses 在装饰时需要模块已登记
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rel = _load_release()


def test_parse_and_bump():
    assert rel.parse_semver("0.1.3") == (0, 1, 3)
    assert rel.parse_semver("v1.2.3") == (1, 2, 3)
    assert rel.bump_semver("0.1.3", "patch") == "0.1.4"
    assert rel.bump_semver("0.1.3", "minor") == "0.2.0"
    assert rel.bump_semver("0.1.3", "major") == "1.0.0"
    assert rel.bump_semver("0.1.3", "0.2.1") == "0.2.1"
    with pytest.raises(ValueError):
        rel.parse_semver("1.2")


def test_classify_conventional_commits():
    groups = rel.classify_commits(
        [
            "feat: 添加消息关注板块",
            "fix(ui): 修复日历弹层",
            "docs: 更新说明",
            "随便写的提交",
        ]
    )
    assert groups["新增"] == ["添加消息关注板块"]
    assert groups["修复"] == ["修复日历弹层"]
    assert groups["文档"] == ["更新说明"]
    assert groups["其他"] == ["随便写的提交"]


def test_render_changelog_section():
    text = rel.render_changelog_section(
        "0.1.4",
        date(2026, 8, 30),
        {"新增": ["功能 A"], "修复": ["问题 B"]},
        "本版重点：消息联动",
    )
    assert "## [0.1.4] - 2026-08-30" in text
    assert "本版重点：消息联动" in text
    assert "### 新增" in text
    assert "- 功能 A" in text
    assert "### 修复" in text


def test_update_changelog_inserts_unreleased(tmp_path, monkeypatch):
    monkeypatch.setattr(rel, "CHANGELOG_FILE", tmp_path / "CHANGELOG.md")
    (tmp_path / "CHANGELOG.md").write_text(
        "# 变更日志\n\n## [未发布]\n\n## [0.1.3] - 2026-08-30\n\n- old\n",
        encoding="utf-8",
    )
    section = "## [0.1.4] - 2026-08-31\n\n### 新增\n\n- x\n"
    rel.update_changelog("0.1.4", section)
    body = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert body.index("## [未发布]") < body.index("## [0.1.4]")
    assert body.index("## [0.1.4]") < body.index("## [0.1.3]")
    assert "- x" in body
