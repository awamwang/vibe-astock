"""proxy_config 落盘与校验。"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from duanxian import paths, proxy_config as pc


@pytest.fixture()
def tmp_profile(monkeypatch):
    root = Path(tempfile.mkdtemp())
    paths.set_profile(root, init_config=True)
    yield root


def test_default_disabled(tmp_profile):
    cfg = pc.export_config()
    assert cfg["enabled"] is False
    assert cfg["url"] == ""
    assert cfg["effective_url"] is None


def test_save_and_effective(tmp_profile, monkeypatch):
    monkeypatch.delenv("VR_PULSE_PROXY", raising=False)
    saved = pc.save_config(enabled=True, url="socks5://127.0.0.1:7881")
    assert saved["enabled"] is True
    assert saved["url"] == "socks5://127.0.0.1:7881"
    assert saved["effective_url"] == "socks5://127.0.0.1:7881"
    assert saved["effective_source"] == "config"
    assert pc.get_configured_url() == "socks5://127.0.0.1:7881"


def test_env_overrides_config(tmp_profile, monkeypatch):
    pc.save_config(enabled=True, url="socks5://127.0.0.1:7881")
    monkeypatch.setenv("VR_PULSE_PROXY", "socks5://127.0.0.1:9999")
    cfg = pc.export_config()
    assert cfg["effective_url"] == "socks5://127.0.0.1:9999"
    assert cfg["effective_source"] == "env"


def test_reject_bad_url(tmp_profile):
    with pytest.raises(pc.ProxyConfigError):
        pc.save_config(enabled=True, url="ftp://x")
    with pytest.raises(pc.ProxyConfigError):
        pc.save_config(enabled=True, url="")
