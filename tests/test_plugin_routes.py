"""插件 HTTP 路由注册与分发。"""

from __future__ import annotations

import threading

import pytest
from starlette.requests import Request
from starlette.responses import HTMLResponse


@pytest.fixture
def routes():
    from duanxian import plugin_routes as pr

    pr.clear_all()
    yield pr
    pr.clear_all()


def _request(method: str = "GET", path: str = "/plugin/p1") -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 9),
        "server": ("127.0.0.1", 8910),
    })


@pytest.mark.unit
class TestPluginRouteRegistry:
    def test_register_requires_bind(self, routes):
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        with pytest.raises(RuntimeError, match="bind_plugin"):
            reg.register_route("", "首页", html="<p>ok</p>")

    def test_html_page_url_and_dispatch(self, routes):
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("plug1")
        res = reg.register_route("panel", "插件面板", html="<h1>hello</h1>")
        assert res.ok
        assert res.detail == "/plugin/plug1/panel"
        rows = routes.as_route_dicts("plug1")
        assert rows == [{
            "url": "/plugin/plug1/panel",
            "path": "panel",
            "description": "插件面板",
            "methods": ["GET", "HEAD"],
        }]
        resp = routes.dispatch("plug1", "panel", _request(path="/plugin/plug1/panel"))
        assert isinstance(resp, HTMLResponse)
        assert b"hello" in resp.body

    def test_root_path_and_handler_request(self, routes):
        from duanxian.hooks import HookRegistry

        seen: list[str] = []

        def _handler(request: Request):
            seen.append(request.method)
            return {"ok": True, "path": request.url.path}

        reg = HookRegistry()
        reg.bind_plugin("plug1")
        reg.register_route("/", "首页", handler=_handler)
        resp = routes.dispatch("plug1", "", _request())
        assert resp.status_code == 200
        assert seen == ["GET"]
        assert b'"ok":true' in resp.body.replace(b" ", b"")

    def test_rejects_parent_segment(self, routes):
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("plug1")
        with pytest.raises(ValueError, match=r"\.\."):
            reg.register_route("../secret", "x", html="<p>no</p>")

    def test_rejects_missing_body(self, routes):
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("plug1")
        with pytest.raises(ValueError, match="handler 或 html"):
            reg.register_route("x", "x")

    def test_same_path_updates(self, routes):
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("plug1")
        reg.register_route("p", "旧", html="<p>a</p>")
        reg.register_route("p", "新", html="<p>b</p>")
        rows = routes.as_route_dicts("plug1")
        assert len(rows) == 1
        assert rows[0]["description"] == "新"
        resp = routes.dispatch("plug1", "p", _request(path="/plugin/plug1/p"))
        assert b"b" in resp.body

    def test_unknown_and_method_not_allowed(self, routes):
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("plug1")
        reg.register_route("only-get", "只读", html="<p>x</p>")
        miss = routes.dispatch("plug1", "missing", _request(path="/plugin/plug1/missing"))
        assert miss.status_code == 404
        bad = routes.dispatch(
            "plug1", "only-get", _request("POST", "/plugin/plug1/only-get")
        )
        assert bad.status_code == 405

    def test_deactivate_unregisters_routes(self, routes):
        from duanxian.hooks import HookPack, HookRegistry, LoadedPlugin, _deactivate_plugin

        reg = HookRegistry()
        reg.bind_plugin("plug1")
        reg.register_route("", "首页", html="<p>x</p>")
        assert routes.list_for_plugin("plug1")
        lp = LoadedPlugin(
            id="plug1",
            path="/tmp/x.py",
            pack=HookPack(name="t", version="1", schema_bundle="t/1"),
        )
        _deactivate_plugin(lp)
        assert routes.list_for_plugin("plug1") == []
        resp = routes.dispatch("plug1", "", _request())
        assert resp.status_code == 404


@pytest.mark.unit
def test_dispatch_handler_can_list_without_deadlock(routes):
    """handler 内再读注册表不得自死锁（dispatch 须锁外调用）。"""
    from duanxian.hooks import HookRegistry

    def _handler():
        return {"n": len(routes.list_for_plugin("plug1"))}

    reg = HookRegistry()
    reg.bind_plugin("plug1")
    reg.register_route("n", "计数", handler=_handler)

    done = threading.Event()
    err: list[Exception] = []
    out: list[int] = []

    def _run() -> None:
        try:
            resp = routes.dispatch("plug1", "n", _request(path="/plugin/plug1/n"))
            out.append(resp.status_code)
        except Exception as exc:  # noqa: BLE001
            err.append(exc)
        finally:
            done.set()

    t = threading.Thread(target=_run)
    t.start()
    assert done.wait(timeout=2.0), "dispatch 持锁调用 list_for_plugin 自死锁"
    t.join(timeout=0.5)
    assert not t.is_alive()
    assert not err
    assert out == [200]


@pytest.mark.unit
def test_http_dispatch_via_server(routes):
    from fastapi.testclient import TestClient

    from duanxian.hooks import HookRegistry
    import server

    reg = HookRegistry()
    reg.bind_plugin("http1")
    reg.register_route("hi", "问好", html="<p>plugin-hi</p>")
    client = TestClient(server.app)
    r = client.get("/plugin/http1/hi")
    assert r.status_code == 200
    assert "plugin-hi" in r.text
    r404 = client.get("/plugin/http1/nope")
    assert r404.status_code == 404
