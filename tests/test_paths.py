"""profile 落盘根：默认用户主目录；指定后初始化缺失配置。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from duanxian import paths
from duanxian import trade_phase_config as tpc
from duanxian import review_store


@pytest.fixture()
def isolated_profile(tmp_path, monkeypatch):
    """每个用例独立 profile，测完清回默认。"""
    monkeypatch.delenv(paths.ENV_PROFILE, raising=False)
    monkeypatch.delenv(paths.ENV_AGENTS, raising=False)
    monkeypatch.delenv(paths.ENV_ASTOCK, raising=False)
    # 保留测试里可能自设的 VR_DATA_DIR；默认清掉以免串台
    monkeypatch.delenv(paths.ENV_VR, raising=False)
    paths.clear_profile_override()
    yield tmp_path
    paths.clear_profile_override()
    for key in (paths.ENV_PROFILE, paths.ENV_AGENTS, paths.ENV_ASTOCK, paths.ENV_VR):
        monkeypatch.delenv(key, raising=False)
    paths.clear_profile_override()


class TestProfileRoot:
    def test_default_is_home(self, isolated_profile, monkeypatch):
        home = Path(isolated_profile / "fake-home")
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        paths.clear_profile_override()
        assert paths.profile_root() == home
        assert paths.agents_dir() == home / ".duanxian-agents"
        assert paths.research_dir() == home / ".vibe-research"
        assert paths.astock_dir() == home / ".vibe-astock"

    def test_set_profile_rebinds_modules(self, isolated_profile):
        root = isolated_profile / "p1"
        paths.set_profile(root, init_config=True)
        assert paths.profile_root() == root.resolve()
        assert Path(tpc._CONFIG_PATH) == root.resolve() / ".duanxian-agents" / "config" / "trade_phases.json"
        assert Path(review_store.DIR) == root.resolve() / ".duanxian-agents" / "reviews"

    def test_init_creates_missing_configs_once(self, isolated_profile):
        root = isolated_profile / "p2"
        info = paths.set_profile(root, init_config=True)
        cfg = info / ".duanxian-agents" / "config"
        phases = cfg / "trade_phases.json"
        assert phases.is_file()
        payload = json.loads(phases.read_text(encoding="utf-8"))
        assert payload["schema"] == 1
        assert "phases" in payload

        plugins = info / ".vibe-astock" / "plugins.json"
        assert plugins.is_file()

        # 第二次不覆盖
        phases.write_text('{"schema":1,"phases":[{"phase":"keep"}]}', encoding="utf-8")
        paths.ensure_profile_initialized()
        assert json.loads(phases.read_text(encoding="utf-8"))["phases"][0]["phase"] == "keep"

    def test_env_vibe_profile(self, isolated_profile, monkeypatch):
        root = isolated_profile / "env-p"
        root.mkdir()
        monkeypatch.setenv(paths.ENV_PROFILE, str(root))
        paths.clear_profile_override()
        assert paths.profile_root() == root.resolve()
        paths.bootstrap(init_config=True)
        assert (root / ".duanxian-agents" / "config" / "trade_thresholds.json").is_file()

    def test_consume_profile_arg(self, isolated_profile):
        target = isolated_profile / "cli-p"
        target.mkdir()
        rest, got = paths.consume_profile_arg(
            ["--profile", str(target), "2026-08-19"]
        )
        assert got == target.resolve()
        assert rest == ["2026-08-19"]

    def test_vr_data_dir_not_overridden_if_set(self, isolated_profile, monkeypatch):
        root = isolated_profile / "p3"
        vr = isolated_profile / "custom-vr"
        vr.mkdir()
        monkeypatch.setenv(paths.ENV_VR, str(vr))
        paths.set_profile(root, init_config=False)
        assert paths.research_dir() == vr.resolve()
        assert os.environ.get(paths.ENV_VR) == str(vr)
