"""插件键值配置（plugins.plugin-env）测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_ENV_PLUGIN = '''
from __future__ import annotations
import os
from duanxian.hooks import HookPack, HookRegistry, PluginEnvField

SEEN = os.environ.get("PLUGIN_ENV_TOKEN", "")

def on_enable(reg: HookRegistry) -> None:
    reg.report_status("ok", reg.plugin_env().get("PLUGIN_ENV_TOKEN", ""))

PACK = HookPack(
    name="env-test",
    version="1.0.0",
    schema_bundle="t/1",
    env_fields=(PluginEnvField("PLUGIN_ENV_TOKEN", "令牌", secret=True),),
    on_enable=on_enable,
)
'''


@pytest.fixture
def plugin_home(tmp_path, monkeypatch):
    from duanxian import plugin_store as ps

    reg_dir = tmp_path / "vibe-astock"
    reg_dir.mkdir()
    monkeypatch.setattr(ps, "_USER_DIR", str(reg_dir))
    monkeypatch.setattr(ps, "_REGISTRY_FILE", str(reg_dir / "plugins.json"))
    return reg_dir


@pytest.mark.unit
class TestPluginEnvFile:
    def test_roundtrip_and_sibling_of_registry(self, plugin_home):
        from duanxian import plugin_env as penv

        path = penv.env_file()
        assert path.endswith("plugins.plugin-env")
        assert Path(path).parent == plugin_home

        saved = penv.save_section("aaaa1111", {
            "APP_TOKEN": 'say "hi" #not',
            "EMPTY": "",
            "NOTE": "line1\nline2",
        })
        assert saved["APP_TOKEN"] == 'say "hi" #not'
        again = penv.load_section("aaaa1111")
        assert again == saved
        text = Path(path).read_text(encoding="utf-8")
        assert "[aaaa1111]" in text
        assert "APP_TOKEN=" in text

    def test_sections_stay_independent(self, plugin_home):
        from duanxian import plugin_env as penv

        penv.save_section("aaaa1111", {"A": "1"})
        penv.save_section("bbbb2222", {"B": "2"})
        penv.save_section("aaaa1111", {"A": "3"})
        assert penv.load_section("bbbb2222") == {"B": "2"}
        assert penv.load_section("aaaa1111") == {"A": "3"}
        penv.delete_section("aaaa1111")
        assert penv.load_section("aaaa1111") == {}
        assert penv.section_exists("bbbb2222")
        assert not penv.section_exists("aaaa1111")

    def test_rejects_bad_key(self, plugin_home):
        from duanxian import plugin_env as penv

        with pytest.raises(ValueError, match="配置键无效"):
            penv.save_section("aaaa1111", {"bad-key": "1"})
        with pytest.raises(ValueError, match="字符串"):
            penv.save_section("aaaa1111", {"OK": 1})

    def test_uninstall_drops_only_that_section(self, plugin_home):
        from duanxian import plugin_env as penv
        from duanxian import plugin_store as ps

        first = plugin_home / "a.py"
        second = plugin_home / "b.py"
        src = _ENV_PLUGIN
        first.write_text(src, encoding="utf-8")
        second.write_text(src.replace("env-test", "env-test-b"), encoding="utf-8")
        rec_a = ps.register(str(first), enabled=False)
        rec_b = ps.register(str(second), enabled=False)
        penv.save_section(rec_a.id, {"PLUGIN_ENV_TOKEN": "a"})
        penv.save_section(rec_b.id, {"PLUGIN_ENV_TOKEN": "b"})
        ps.uninstall(rec_a.id)
        assert not penv.section_exists(rec_a.id)
        assert penv.load_section(rec_b.id)["PLUGIN_ENV_TOKEN"] == "b"
        assert penv.env_file().endswith("plugins.plugin-env")

    def test_apply_to_environ_sets_and_clears(self, plugin_home, monkeypatch):
        from duanxian import plugin_env as penv

        monkeypatch.setenv("PLUGIN_ENV_TOKEN", "old")
        penv.save_section("aaaa1111", {"PLUGIN_ENV_TOKEN": "new"})
        penv.apply_to_environ("aaaa1111")
        assert os.environ["PLUGIN_ENV_TOKEN"] == "new"
        penv.save_section("aaaa1111", {"PLUGIN_ENV_TOKEN": ""})
        penv.apply_to_environ("aaaa1111")
        assert "PLUGIN_ENV_TOKEN" not in os.environ

    def test_describe_fields_and_enable_reads_env(self, plugin_home, monkeypatch):
        import sys

        from duanxian import plugin_env as penv
        from duanxian import plugin_status as pst
        from duanxian import plugin_store as ps
        from duanxian.hooks import _module_name, apply_plugin_disable, apply_plugin_enable

        monkeypatch.delenv("PLUGIN_ENV_TOKEN", raising=False)
        path = plugin_home / "envplug.py"
        path.write_text(_ENV_PLUGIN, encoding="utf-8")
        rec = ps.register(str(path), enabled=False)
        penv.save_section(rec.id, {"PLUGIN_ENV_TOKEN": "secret-1"})

        info = penv.describe(rec.id, str(path))
        assert info["file"].endswith("plugins.plugin-env")
        assert info["env"]["PLUGIN_ENV_TOKEN"] == "secret-1"
        assert info["fields"][0]["key"] == "PLUGIN_ENV_TOKEN"
        assert info["fields"][0]["secret"] is True
        assert info["error"] == ""

        ps.set_enabled(rec.id, True)
        assert apply_plugin_enable(rec.id) is not None
        try:
            st = pst.get_status(rec.id)
            assert st is not None
            assert st.message == "secret-1"
            mod = sys.modules[_module_name(rec.id)]
            assert mod.SEEN == "secret-1"
            assert os.environ["PLUGIN_ENV_TOKEN"] == "secret-1"
        finally:
            apply_plugin_disable(rec.id)
            os.environ.pop("PLUGIN_ENV_TOKEN", None)

    def test_describe_prefills_from_plugin_dotenv(self, plugin_home):
        from duanxian import plugin_env as penv
        from duanxian import plugin_store as ps

        path = plugin_home / "envplug.py"
        path.write_text(_ENV_PLUGIN, encoding="utf-8")
        rec = ps.register(str(path), enabled=False)
        (plugin_home / ".env").write_text(
            'PLUGIN_ENV_TOKEN="from-dotenv"\nUNRELATED=skip\n',
            encoding="utf-8",
        )

        info = penv.describe(rec.id, str(path))
        assert info["env"]["PLUGIN_ENV_TOKEN"] == "from-dotenv"
        assert "UNRELATED" not in info["env"]
        assert info["dotenv_file"].endswith(".env")
        assert Path(info["dotenv_file"]).is_file()

        penv.save_section(rec.id, {"PLUGIN_ENV_TOKEN": "from-ui"})
        info = penv.describe(rec.id, str(path))
        assert info["env"]["PLUGIN_ENV_TOKEN"] == "from-ui"

        penv.save_section(rec.id, {"PLUGIN_ENV_TOKEN": ""})
        info = penv.describe(rec.id, str(path))
        assert info["env"]["PLUGIN_ENV_TOKEN"] == "from-dotenv"

    def test_describe_without_dotenv_keeps_saved_only(self, plugin_home):
        from duanxian import plugin_env as penv
        from duanxian import plugin_store as ps

        path = plugin_home / "envplug.py"
        path.write_text(_ENV_PLUGIN, encoding="utf-8")
        rec = ps.register(str(path), enabled=False)
        info = penv.describe(rec.id, str(path))
        assert info["env"] == {}
        assert info["dotenv_file"] == ""

