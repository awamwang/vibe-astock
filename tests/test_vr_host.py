"""VR host 公开 interface 测试。

CLI 白名单、钉定稿涨停池、合并 / 路径识别 —— 对准 `duanxian.vr_host`；
`server` 再导出仅作薄适配兼容（HTTP 闸仍测 server）。
"""

from __future__ import annotations

import pytest

from duanxian import vr_host


def _live_cli_runtime():
    """`/api/chat` **实际**用的那个 cli_runtime 模块对象"""
    import sys

    import server  # noqa: F401  确保 install() 已把 VR 那套加载进来

    live = sys.modules.get("app")
    assert live is not None and hasattr(live, "cli_runtime"), "VR app 模块没加载"
    return live.cli_runtime


# ---------------------------------------------------------------- 路径识别 / HTTP 闸
@pytest.mark.unit
class TestVrGuard:
    """给并进来的 VR 路由补的两道闸（ 第 6 轮审两条 ，均核实为真）"""

    @pytest.fixture(autouse=True)
    def _clean_job(self):
        import server

        snap = dict(server._job)
        server._job.update(running=False, date=None, job_id=None, error=None,
                           started=None, elapsed=0, finished_at=None)
        yield
        server._job.clear()
        server._job.update(snap)

    def test_vr_paths_recognised_including_params(self):
        """路径识别要覆盖带参数的模板，且**不能误伤我们自己的路由**。"""
        assert vr_host._VR_PATH_RES, "没收集到 VR 路径正则"
        for p in ("/api/portfolio/holding", "/api/myreports/abc123",
                  "/api/radar/refresh", "/api/quote", "/api/indices"):
            assert vr_host._is_vr_path(p), f"{p} 应识别为 VR 路由"
        for p in ("/api/review/latest", "/api/risk/report", "/api/journal/stats",
                  "/api/drift", "/api/modes"):
            assert not vr_host._is_vr_path(p), f"{p} 是我们自己的，不该被闸拦"
        # server 再导出须同一集合
        import server
        assert server._is_vr_path is vr_host._is_vr_path

    def test_all_vr_mutations_are_covered(self):
        """VR 的**每一条**写操作都必须落在闸的覆盖面内 —— 漏一条就是一个裸的写接口。"""
        import pathlib
        import re

        muts = set()
        for f in pathlib.Path("vr").glob("*.py"):
            muts |= set(re.findall(r'@app\.(?:post|delete|put)\("([^"]+)"',
                                   f.read_text(encoding="utf-8")))
        assert muts, "没解析到 VR 的写操作（测试失效了）"
        for path in muts:
            probe = re.sub(r"\{[^}]+\}", "X", path)   # 参数位填个占位
            assert vr_host._is_vr_path(probe), f"写操作 {path} 没被闸覆盖"

    def test_guard_middleware_is_registered(self):
        import server

        names = [getattr(m, "kwargs", {}).get("dispatch", None) or m for m in
                 server.app.user_middleware]
        src = __import__("inspect").getsource(server)
        assert "_vr_guard" in src
        assert server.app.user_middleware, "middleware 没注册上"

    @staticmethod
    def _vr_path() -> str:
        return "/api/quote"

    def test_guard_only_touches_vr_paths(self, monkeypatch):
        """闸只作用于 VR 路径 —— 我们自有路由已在 handler 里自校验，再来一遍
        会把 GET 也卡住。"""
        monkeypatch.setattr(vr_host, "_VR_API_KEY", "k")

        deny = lambda: False    # noqa: E731  来源不合法
        assert vr_host.vr_guard_error("/api/review/run", "POST", "", deny) is None
        assert vr_host.vr_guard_error("/api/review/latest", "GET", "", deny) is None

    def test_origin_gate_only_blocks_mutations(self, monkeypatch):
        """来源闸只卡写操作：GET 被卡住的话，看盘的人换个域名访问就整块打不开。"""
        monkeypatch.setattr(vr_host, "_VR_API_KEY", "")
        deny = lambda: False        # noqa: E731
        allow = lambda: True        # noqa: E731

        assert vr_host.vr_guard_error(self._vr_path(), "GET", "", deny) is None
        assert vr_host.vr_guard_error(self._vr_path(), "POST", "", deny) == (403, "非法来源")
        assert vr_host.vr_guard_error(self._vr_path(), "POST", "", allow) is None

    def test_api_key_gate_exempts_preflight_and_health(self, monkeypatch):
        """设了口令时：预检要放过（否则浏览器写操作全挂），健康检查豁免（同上游口径）。"""
        monkeypatch.setattr(vr_host, "_VR_API_KEY", "k")
        allow = lambda: True        # noqa: E731

        assert vr_host.vr_guard_error(self._vr_path(), "GET", "", allow)[0] == 401
        assert vr_host.vr_guard_error(self._vr_path(), "GET", "Bearer k", allow) is None
        assert vr_host.vr_guard_error(self._vr_path(), "OPTIONS", "", allow) is None
        assert vr_host.vr_guard_error("/api/health", "GET", "", allow) is None

    def test_no_api_key_configured_means_no_401(self, monkeypatch):
        """没配口令就是单机自用：不能因此把所有 VR 请求都判成未授权。"""
        monkeypatch.setattr(vr_host, "_VR_API_KEY", "")

        assert vr_host.vr_guard_error(self._vr_path(), "GET", "", lambda: True) is None

    def test_origin_check_is_not_run_for_reads(self, monkeypatch):
        """读请求不该去算来源 —— 每个请求都走这道 middleware，白算就是白花。"""
        monkeypatch.setattr(vr_host, "_VR_API_KEY", "")
        calls = []

        vr_host.vr_guard_error(self._vr_path(), "GET", "", lambda: calls.append(1) or True)
        assert calls == []

    def test_server_middleware_delegates_the_decision(self):
        """server 只做 HTTP 管道：判定不许在 middleware 里再写一遍。"""
        import inspect

        import server

        src = inspect.getsource(server._vr_guard)
        assert "vr_guard_error" in src
        for leaked in ("_is_vr_path", "Bearer", "_MUTATING"):
            assert leaked not in src, f"闸的判定又漏回 server 了：{leaked}"


# ---------------------------------------------------------------- 用户数据防护
@pytest.mark.unit
class TestVrUserDataGuard:
    """VR 用户数据防护（ 第 6 轮 vr/ 专项发现，已核实为真的数据丢失风险）"""

    def test_upstream_really_swallows_corruption(self):
        """先确认上游行为没变 —— 这条防护的前提。上游改了这条测试要跟着改。"""
        import pathlib

        src = pathlib.Path("vr/portfolio.py").read_text(encoding="utf-8")
        assert "except (FileNotFoundError, json.JSONDecodeError)" in src
        assert '"holdings": []' in src, "上游仍把损坏当成空持仓"

    def test_good_file_gets_dated_backup(self, tmp_path, monkeypatch):
        import json as _json
        import os

        pf = tmp_path / "portfolio.json"
        pf.write_text(_json.dumps({"holdings": [{"code": "002463"}]}), encoding="utf-8")
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        vr_host._guard_vr_userdata()
        baks = list(tmp_path.glob("portfolio.good-*.json"))
        assert len(baks) == 1
        assert _json.loads(baks[0].read_text(encoding="utf-8"))["holdings"][0]["code"] == "002463"

    def test_empty_file_never_clobbers_a_nonempty_backup(self, tmp_path, monkeypatch):
        """走完整条灾难链：**备份绝不能被"损坏后写成的空文件"覆盖**"""
        import json as _json
        import os

        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        pf = tmp_path / "portfolio.json"

        # ① 有真实持仓 → 留备份
        pf.write_text(_json.dumps({"holdings": [{"code": "600000"}, {"code": "000001"}]}),
                      encoding="utf-8")
        vr_host._guard_vr_userdata()
        # ② 损坏
        pf.write_text("{ 半截坏", encoding="utf-8")
        vr_host._guard_vr_userdata()
        # ③ VR 写成合法的空 JSON
        pf.write_text(_json.dumps({"holdings": [], "last_refresh": None}), encoding="utf-8")
        # ④ 再启动
        vr_host._guard_vr_userdata()

        survived = [b for b in tmp_path.glob("portfolio.good-*.json")
                    if (_json.loads(b.read_text(encoding="utf-8")) or {}).get("holdings")]
        assert survived, "非空备份被空文件毁了 —— 恰好在最需要它的时候"
        assert len(_json.loads(survived[0].read_text(encoding="utf-8"))["holdings"]) == 2

    def test_origin_whitelist_is_extensible(self):
        """公网部署时浏览器 Origin 是真实域名 → 写操作会全 403

        Origin 闸仍在 server（HTTP-only）；此处只钉白名单可扩展。
        """
        import importlib
        import os

        import server

        assert "localhost" in server._ALLOWED_HOSTS
        os.environ["VIBE_ALLOW_HOSTS"] = "myhost.example, www.myhost.example"
        try:
            reloaded = importlib.reload(server)
            assert "myhost.example" in reloaded._ALLOWED_HOSTS
            assert "www.myhost.example" in reloaded._ALLOWED_HOSTS
            assert "127.0.0.1" in reloaded._ALLOWED_HOSTS, "本机必须始终在白名单里"
        finally:
            del os.environ["VIBE_ALLOW_HOSTS"]
            importlib.reload(server)

    def test_corrupt_file_is_preserved_and_alerted(self, tmp_path, monkeypatch, capsys):
        """损坏时必须①另存原始字节②告警。原始字节是唯一的恢复依据。"""
        import os

        pf = tmp_path / "portfolio.json"
        pf.write_text("{ 半截坏 JSON", encoding="utf-8")
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        vr_host._guard_vr_userdata()
        saved = list(tmp_path.glob("portfolio.corrupt-*.json"))
        assert len(saved) == 1, "损坏文件的原始字节必须另存"
        assert saved[0].read_text(encoding="utf-8") == "{ 半截坏 JSON", "必须是原始字节"
        err = capsys.readouterr().err
        assert "🔴" in err and "无法解析" in err

    def test_alert_goes_to_stderr_with_flush(self):
        """告警必须走 stderr + flush"""
        import inspect

        src = inspect.getsource(vr_host._alert)
        assert "file=sys.stderr" in src and "flush=True" in src
        # 关键告警都要走 _alert，不能用裸 print（实现在 vr_host）
        full = inspect.getsource(vr_host)
        for marker in ("🔴 VR 持仓文件无法解析", "⚠️ VR 后端并入失败"):
            idx = full.index(marker)
            head = full[max(0, idx - 120):idx]
            assert "_alert(" in head, f"「{marker}」没走 _alert，会被缓冲吞掉"


# ---------------------------------------------------------------- CLI 白名单
@pytest.mark.unit
class TestBlockedCliRemovedFromRuntime:
    """第 7 轮 ：禁用必须在**服务端**生效，不是只在前端灰按钮"""

    def test_unsafe_kinds_are_gone_from_cli_defs(self):
        """能力必须在运行时字典里就不存在"""
        cli_runtime = _live_cli_runtime()
        assert vr_host._ALLOWED_CLI_KINDS, "白名单不能是空的（那会把 claude 也摘掉）"
        for kind in ("qwen", "deepseek", "codex"):
            assert kind not in cli_runtime._CLI_DEFS, f"{kind} 还在运行时字典里 → 仍可被调用"
        assert "claude" in cli_runtime._CLI_DEFS, "claude 是保留的那个，不能连它一起摘"

    def test_both_module_copies_are_stripped(self):
        """两份拷贝都得摘干净 —— 只摘一份就等于没摘。"""
        import sys

        assert vr_host._cli_runtime_modules(), "应当能找到 cli_runtime 模块"
        copies = [m for name, m in list(sys.modules.items())
                  if m is not None and (name == "cli_runtime" or name.endswith(".cli_runtime"))
                  and hasattr(m, "_CLI_DEFS")]
        for m in copies:
            leftover = set(m._CLI_DEFS) - set(vr_host._ALLOWED_CLI_KINDS)
            assert not leftover, f"{m.__name__} 这份还剩 {sorted(leftover)}"

    def test_every_cli_entry_point_refuses(self):
        """摘掉 dict 后，三个入口（detect/run/run_stream）全部拒绝 —— 这才是「单一收口」的意义。"""
        cli_runtime = _live_cli_runtime()

        assert cli_runtime.detect_cli("codex") is None      # vr/app.py 据此返回 400
        assert "codex" not in cli_runtime.supported_kinds()
        for fn in (cli_runtime.run_cli, cli_runtime.run_cli_stream):
            with pytest.raises(RuntimeError):
                out = fn("codex", "sys", "user")
                list(out)  # run_cli_stream 是生成器，要迭代才会执行

    def test_no_other_call_path_bypasses_the_dict(self):
        """清点出口：所有 CLI 调用都得经过 `_CLI_DEFS`，这道闸就漏了"""
        import pathlib
        import re

        hits = []
        for p in pathlib.Path("vr").glob("*.py"):
            if p.name == "cli_runtime.py":
                continue
            for m in re.finditer(r"cli_runtime\.(\w+)", p.read_text(encoding="utf-8")):
                hits.append(m.group(1))
        # 只允许这三个 —— 它们内部都是 `_CLI_DEFS.get(kind)` 开头
        assert set(hits) <= {"detect_cli", "run_cli", "run_cli_stream", "supported_kinds"}, \
            f"出现了没经过 _CLI_DEFS 的 CLI 调用：{sorted(set(hits))}"

    def test_frontend_drops_stale_blocked_config_on_load(self):
        """前端也要在**读取**时丢掉旧配置（不是只在保存时挡）。"""
        import pathlib

        llm = pathlib.Path("frontend/src/lib/llm.ts").read_text(encoding="utf-8")
        load_body = llm[llm.index("export function loadLlm"):llm.index("export function saveLlm")]
        assert "serverAllowsCli" in load_body, "loadLlm 要按服务端答案拦"
        assert "staleBlockedProvider" in llm, "要能告诉用户「原来那个为什么没了」"

    def test_settings_explains_why_the_old_choice_vanished(self):
        """失效也是坏体验：设置页要写明原因"""
        import pathlib

        s = pathlib.Path("frontend/src/pages/Settings.tsx").read_text(encoding="utf-8")
        assert "staleBlocked" in s and "已被禁用" in s

    def test_gate_is_a_whitelist_not_a_blacklist(self):
        """极性：默认必须是"拒绝"。

        黑名单的默认是放行 —— `vr/` 是上游代码，它日后新增一个带 `--yolo` 的 CLI，
        黑名单没写就自动可用，而且**没人会收到提示**。
        """
        import inspect

        assert vr_host._ALLOWED_CLI_KINDS == frozenset({"claude"})
        src = inspect.getsource(vr_host._disable_unsafe_clis)
        assert "not in _ALLOWED_CLI_KINDS" in src, "要按白名单摘，不能按黑名单摘"

    def test_upstream_newcomer_is_blocked_and_alerted(self):
        """上游新增一个 CLI：白名单挡住它，并且**出声**。"""
        cli_runtime = _live_cli_runtime()
        alerts: list[str] = []
        orig_defs = dict(cli_runtime._CLI_DEFS)
        try:
            cli_runtime._CLI_DEFS["gemini"] = {"bins": ["gemini"], "delivery": "stdin",
                                               "build_args": lambda _: ["--yolo"], "env": {}}
            _orig_alert = vr_host._alert
            vr_host._alert = alerts.append  # type: ignore[assignment]
            try:
                removed = vr_host._disable_unsafe_clis()
            finally:
                vr_host._alert = _orig_alert  # type: ignore[assignment]
            assert "gemini" in removed, "上游新来的必须被摘掉"
            assert "gemini" not in cli_runtime._CLI_DEFS
            assert any("gemini" in a for a in alerts), "被摘掉了还得有人知道"
        finally:
            cli_runtime._CLI_DEFS.clear()
            cli_runtime._CLI_DEFS.update(orig_defs)

    def test_blocked_lists_agree_across_layers(self):
        """两层口径要一致：前端灰掉的，后端也得摘掉（反之亦然）"""
        import pathlib
        import re

        cli_runtime = _live_cli_runtime()
        ts = pathlib.Path("frontend/src/lib/ai-models.ts").read_text(encoding="utf-8")
        for block in re.findall(r"\{[^{}]*\}", ts[ts.index("export const aiModels"):]):
            m = re.search(r'provider:\s*"cli-([a-z]+)"', block)
            if not m:
                continue
            kind, fe_blocked = m.group(1), "blocked:" in block
            be_usable = kind in cli_runtime._CLI_DEFS
            assert fe_blocked != be_usable, (
                f"{kind}：前端{'禁用' if fe_blocked else '可选'}，"
                f"后端{'可用' if be_usable else '已摘'} —— 两层口径不一致")
            if not fe_blocked:
                assert kind in vr_host._ALLOWED_CLI_KINDS


@pytest.mark.unit
class TestNoDuplicateVrAppImport:
    """第 8 轮 ：别把 `vr/app.py` 加载第二遍"""

    def test_only_one_app_module_is_loaded(self):
        import sys

        import server  # noqa: F401

        assert sys.modules.get("app") is not None, "VR app 应当以 `app` 加载"
        assert "vr.app" not in sys.modules, \
            "vr.app 被导入了 → vr/app.py 跑了两遍，后台调度线程会翻倍"

    def test_only_one_scheduler_thread(self):
        import threading

        import server  # noqa: F401

        loops = [t for t in threading.enumerate() if "loop" in t.name]
        assert len(loops) <= 1, f"起了 {len(loops)} 个调度线程：{[t.name for t in loops]}"

    def test_source_does_not_import_vr_app(self):
        """连源码里都不该出现 —— 这个坑靠"运行时刚好没触发"是守不住的。"""
        import pathlib
        import re

        stmt = re.compile(r"^\s*(?:import\s+vr\.app|from\s+vr\.app\s+import|from\s+vr\s+import\s+app)\b")
        for f in ("server.py", "duanxian/vr_host.py", "tests/test_vr_host.py"):
            for n, line in enumerate(pathlib.Path(f).read_text(encoding="utf-8").splitlines(), 1):
                assert not stmt.match(line), f"{f}:{n} 有 `import vr.app`：{line.strip()}"


@pytest.mark.unit
class TestUnsafeCliOptIn:
    """`VIBE_ALLOW_UNSAFE_CLI` —— 给"只有 Qwen 订阅、没有 Claude"的人留的口子。

    默认仍然拒绝；放开必须是运行服务的人的一个显式动作，且启动时要吼一声。
    """

    def test_default_is_claude_only(self, monkeypatch):
        monkeypatch.delenv("VIBE_ALLOW_UNSAFE_CLI", raising=False)
        assert vr_host._opted_in_clis() == frozenset()
        assert vr_host._SAFE_CLI_KINDS == frozenset({"claude"})

    def test_env_parsing(self, monkeypatch):
        monkeypatch.setenv("VIBE_ALLOW_UNSAFE_CLI", " qwen , deepseek ,, ")
        assert vr_host._opted_in_clis() == frozenset({"qwen", "deepseek"})

    def test_startup_shouts_about_what_was_opened(self):
        """放开了危险 CLI 就必须说清放开了什么 —— 无声的放行最危险。"""
        import pathlib

        src = pathlib.Path("server.py").read_text(encoding="utf-8")
        i = src.index("if _opted_in_clis():")
        block = src[i:i + 700]
        assert "VIBE_ALLOW_UNSAFE_CLI 已放开" in block
        assert "读写文件" in block and "原样进 prompt" in block, "要说清代价，不只报个名字"

    def test_env_name_says_unsafe(self):
        """变量名本身就得是警告 —— 不能叫 VIBE_EXTRA_CLI 这种中性名字。"""
        import server

        assert "UNSAFE" in server.api_cli_available()["optInEnv"]

    def test_opt_in_actually_reaches_the_allow_set(self, monkeypatch):
        """光测"解析对了"是 —— 要测解析结果**到达**了 `_ALLOWED_CLI_KINDS`"""
        import importlib

        import server

        monkeypatch.setenv("VIBE_ALLOW_UNSAFE_CLI", "qwen")
        try:
            r = importlib.reload(server)
            assert "qwen" in r._ALLOWED_CLI_KINDS, "opt-in 没到达放行集合"
            assert "claude" in r._ALLOWED_CLI_KINDS, "安全那个不能因此丢掉"
            assert "deepseek" not in r._ALLOWED_CLI_KINDS, "没放开的不能顺带放进来"
        finally:
            monkeypatch.delenv("VIBE_ALLOW_UNSAFE_CLI", raising=False)
            importlib.reload(server)   # 复位，别漏给别的测试

    def test_bins_snapshot_is_reentrant(self):
        """`_disable_unsafe_clis()` 必须可重入。

        第二次跑时 `_CLI_DEFS` 已经被摘空，就地重建快照只会得到残缺的（只剩 claude）
        → 之后所有被禁的 kind 都被 `/api/cli/available` 误报成"没装"。
        所以快照寄存在不会被 reload 的 `cli_runtime` 模块上。
        """
        vr_host._ALL_CLI_BINS.clear()
        vr_host._disable_unsafe_clis()
        assert set(vr_host._ALL_CLI_BINS) >= {"claude", "qwen", "deepseek", "codex"}, \
            f"快照残缺：{sorted(vr_host._ALL_CLI_BINS)}"


# ---------------------------------------------------------------- 钉定稿涨停池 / 合并源
@pytest.mark.unit
class TestPinPoolToSettledSession:
    """涨停池可见范围钉在已定稿场次；未定稿日视为尚无池子。"""

    def test_unsettled_date_returns_empty(self, monkeypatch):
        import sys
        import types

        calls = []

        def orig(kind, date, sort, *a, **kw):
            calls.append(date)
            return [{"code": "000001"}]

        fake = types.ModuleType("astock")
        fake.em_zt_topic_pool = orig
        fake._pool_pinned = False
        monkeypatch.setitem(sys.modules, "astock", fake)
        assert vr_host._pin_pool_to_settled_session() == 1
        monkeypatch.setattr("duanxian.trade_calendar.is_settled", lambda d: False)
        assert fake.em_zt_topic_pool("zt", "20260820", "x") == []
        assert calls == []  # 未定稿不应打原函数
        assert fake._pool_unpinned is orig

    def test_settled_date_passes_through(self, monkeypatch):
        import sys
        import types

        def orig(kind, date, sort, *a, **kw):
            return [{"code": "000002"}]

        fake = types.ModuleType("astock")
        fake.em_zt_topic_pool = orig
        fake._pool_pinned = False
        monkeypatch.setitem(sys.modules, "astock", fake)
        assert vr_host._pin_pool_to_settled_session() == 1
        monkeypatch.setattr("duanxian.trade_calendar.is_settled", lambda d: True)
        assert fake.em_zt_topic_pool("zt", "20260819", "x") == [{"code": "000002"}]

    def test_pin_is_idempotent(self, monkeypatch):
        import sys
        import types

        fake = types.ModuleType("astock")
        fake.em_zt_topic_pool = lambda *a, **k: []
        fake._pool_pinned = True
        monkeypatch.setitem(sys.modules, "astock", fake)
        assert vr_host._pin_pool_to_settled_session() == 1


@pytest.mark.unit
class TestMergeSource:
    """合并 VR 走 sys.path，禁止 `import vr.app`。"""

    def test_merge_uses_sys_path_insert(self):
        import pathlib

        host = pathlib.Path("duanxian/vr_host.py").read_text(encoding="utf-8")
        assert "sys.path.insert(0, vr_dir)" in host
        assert "import app as vr_app" in host

    def test_server_only_reexports_host(self):
        import pathlib

        src = pathlib.Path("server.py").read_text(encoding="utf-8")
        assert "_merge_vr_routes = _vr_host._merge_vr_routes" in src
        assert "add_middleware" not in src, "不该把 VR 的 CORS 中间件搬过来"
