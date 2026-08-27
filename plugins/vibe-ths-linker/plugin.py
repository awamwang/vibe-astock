"""vibe ↔ ths-linker 桥接插件 —— 经 WebSocket 联动同花顺实例。

依赖：pip install -r plugins/vibe-ths-linker/requirements.txt
环境变量：
  THS_LINKER_WS_URL  默认 ws://127.0.0.1:8765
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from duanxian.hooks import HookPack, HookRegistry

_REQ_FILE = Path(__file__).resolve().parent / "requirements.txt"


try:
    import websocket
except ImportError as exc:
    raise ImportError(
        f"vibe-ths-linker 插件需要 websocket-client：pip install -r {_REQ_FILE}"
    ) from exc

_WS_URL = os.environ.get("THS_LINKER_WS_URL", "ws://127.0.0.1:8765")

_SYNC_INTERVAL = 60.0
_WS_TIMEOUT = 20.0
_DRAIN_TIMEOUT = 2.0


def _ensure_vr_path() -> None:
    import sys

    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        vr_dir = parent / "vr"
        if vr_dir.is_dir() and (parent / "duanxian").is_dir():
            root = str(parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            vr = str(vr_dir)
            if vr not in sys.path:
                sys.path.insert(0, vr)
            return


def _json_sig(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def _normalize_holdings(raw: list[dict] | None) -> tuple[tuple[str, float, float], ...]:
    out: list[tuple[str, float, float]] = []
    for h in raw or []:
        code = str(h.get("code") or "").strip()
        if len(code) != 6 or not code.isdigit():
            continue
        shares = float(h.get("shares") or 0)
        cost = float(h.get("cost") or 0)
        if shares <= 0 or cost <= 0:
            continue
        out.append((code, shares, round(cost, 4)))
    return tuple(sorted(out))


def _account_fields_from_snapshot(snapshot: dict) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    mapping = (
        ("account_name", "account_name"),
        ("account_display", "account_display"),
        ("broker", "broker"),
        ("cash_balance", "cash_balance"),
        ("available", "available"),
        ("withdrawable", "withdrawable"),
        ("frozen", "frozen"),
        ("stock_market_value", "stock_market_value"),
        ("position_pnl", "position_pnl"),
        ("daily_pnl", "daily_pnl"),
        ("daily_pnl_pct", "daily_pnl_pct"),
    )
    for src, dst in mapping:
        val = snapshot.get(src)
        if val is not None and val != "":
            fields[dst] = val
    return fields


class ThsLinkerWsClient:
    """ths-linker WebSocket 客户端（后台读线程 + 请求-响应配对）。"""

    def __init__(self, url: str) -> None:
        self._url = url
        self._ws: websocket.WebSocket | None = None
        self._send_lock = threading.Lock()
        self._response_lock = threading.Lock()
        self._response_queues: list[queue.Queue[dict]] = []
        self._initial_get: dict | None = None
        self._on_push: Callable[[dict], None] | None = None
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None

    def set_push_handler(self, handler: Callable[[dict], None] | None) -> None:
        self._on_push = handler

    def connect(self) -> None:
        self.close()
        try:
            ws = websocket.create_connection(self._url, timeout=_WS_TIMEOUT)
        except (ConnectionRefusedError, ConnectionError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                f"无法连接 ths-linker（{self._url}）：请先启动 ths-linker 服务后再启用本插件"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            err = str(exc).lower()
            if "refused" in err or "10061" in err or "timed out" in err:
                raise RuntimeError(
                    f"无法连接 ths-linker（{self._url}）：请先启动 ths-linker 服务后再启用本插件"
                ) from exc
            raise
        ws.settimeout(1.0)
        self._ws = ws
        self._stop.clear()
        self._reader = threading.Thread(target=self._reader_loop, name="ths-linker-ws-reader", daemon=True)
        self._reader.start()

    def close(self) -> None:
        self._stop.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None
        if self._reader is not None and self._reader.is_alive() and self._reader is not threading.current_thread():
            self._reader.join(timeout=2.0)
        self._reader = None
        with self._response_lock:
            self._response_queues.clear()
            self._initial_get = None

    @staticmethod
    def _is_push(msg: dict) -> bool:
        mtype = msg.get("type")
        action = msg.get("action")
        return (mtype == "stock_code" and action == "push") or (
            mtype == "trade" and action == "push"
        )

    def _deliver_push(self, msg: dict) -> None:
        if self._on_push:
            self._on_push(msg)

    def _enqueue_response(self, msg: dict) -> None:
        with self._response_lock:
            if self._response_queues:
                self._response_queues[0].put(msg)
            elif msg.get("type") == "stock_code" and msg.get("action") == "get":
                self._initial_get = msg

    def _reader_loop(self) -> None:
        while not self._stop.is_set():
            ws = self._ws
            if ws is None:
                break
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:  # noqa: BLE001
                if not self._stop.is_set():
                    break
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if self._is_push(msg):
                self._deliver_push(msg)
                continue
            self._enqueue_response(msg)

    def take_initial_get(self) -> dict | None:
        with self._response_lock:
            msg = self._initial_get
            self._initial_get = None
            return msg

    def request(
        self,
        payload: dict,
        *,
        expect_type: str | None = None,
        expect_types: tuple[str, ...] | None = None,
    ) -> dict:
        allowed = set(expect_types or ([] if expect_type is None else [expect_type]))
        resp_q: queue.Queue[dict] = queue.Queue()
        with self._response_lock:
            self._response_queues.append(resp_q)
        try:
            with self._send_lock:
                if self._ws is None:
                    self.connect()
                assert self._ws is not None
                action = payload.get("action")
                self._ws.send(json.dumps(payload, ensure_ascii=False))
            deadline = time.monotonic() + _WS_TIMEOUT
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    msg = resp_q.get(timeout=min(remaining, 1.0))
                except queue.Empty:
                    continue
                mtype = msg.get("type")
                if allowed and mtype not in allowed:
                    continue
                if action and msg.get("action") and msg.get("action") != action:
                    continue
                return msg
            raise TimeoutError(f"等待 {allowed or '响应'} 超时：{payload}")
        finally:
            with self._response_lock:
                if resp_q in self._response_queues:
                    self._response_queues.remove(resp_q)

    def drain_initial(self) -> dict | None:
        """连接后读取服务端主动推送的 stock_code get。"""
        deadline = time.monotonic() + _DRAIN_TIMEOUT
        while time.monotonic() < deadline:
            snap = self.take_initial_get()
            if snap is not None:
                return snap
            time.sleep(0.05)
        return None


class ThsLinkerBridge:
    def __init__(self, reg: HookRegistry, plugin_id: str) -> None:
        self._reg = reg
        self._plugin_id = plugin_id
        self._client = ThsLinkerWsClient(_WS_URL)
        self._client.set_push_handler(self._on_ws_push)
        self._instance: dict | None = None
        self._ths_dir = ""
        self._instance_title = ""
        self._last_stock_code: str | None = None
        self._last_watchlist: tuple[str, ...] | None = None
        self._last_portfolio_sig: str | None = None
        self._last_risk_sig: str | None = None
        self._ready = False
        self._pending_pushes: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._client.connect()
        snap = self._client.drain_initial()
        if snap is None:
            snap = self._client.request(
                {"type": "stock_code", "action": "get"},
                expect_types=("stock_code", "stock_code_result"),
            )
        instances = snap.get("instances") or []
        if not instances:
            raise RuntimeError(
                "ths-linker 无可用实例：请启动同花顺并在 ths-linker「监听」页勾选实例后启动"
            )
        self._instance = instances[0]
        self._ths_dir = str(self._instance.get("ths_dir") or "").strip()
        self._instance_title = str(self._instance.get("title") or "").strip()
        if not self._ths_dir:
            raise RuntimeError("ths-linker 实例缺少 ths_dir，无法定位同花顺安装目录")
        self._apply_stock_from_get(snap)
        self._ready = True
        self._flush_pending_pushes()
        try:
            self._sync_watchlist()
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ [vibe-ths-linker] 启动自选股同步失败：{exc}")
        self._thread = threading.Thread(target=self._run_loop, name="ths-linker-bridge", daemon=True)
        self._thread.start()
        detail = f"pid={self._instance.get('id')} ths_dir={self._ths_dir}"
        print(f"[vibe-ths-linker] 已绑定实例 {detail}")
        self._reg.report_status("ok", "已连接 ths-linker", detail)

    def stop(self) -> None:
        self._stop.set()
        self._ready = False
        self._client.close()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._report_status("off", "已停用")

    def _report_status(self, level: str, message: str, detail: str | None = None) -> None:
        from duanxian import plugin_status as ps

        if self._plugin_id:
            ps.set_status(self._plugin_id, level, message, detail)

    def _run_loop(self) -> None:
        last_sync = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                if now - last_sync >= _SYNC_INTERVAL:
                    self._sync_watchlist()
                    self._sync_risk_control()
                    last_sync = now
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                print(f"⚠️ [vibe-ths-linker] 同步异常：{err}")
                traceback.print_exc()
                self._report_status("warn", f"同步异常：{err}", traceback.format_exc())
                try:
                    self._ready = False
                    self._client.connect()
                    snap = self._client.drain_initial()
                    if snap is None:
                        snap = self._client.request(
                            {"type": "stock_code", "action": "get"},
                            expect_types=("stock_code", "stock_code_result"),
                        )
                    if snap is not None:
                        self._apply_stock_from_get(snap)
                    self._ready = True
                    self._flush_pending_pushes()
                except Exception as re_exc:  # noqa: BLE001
                    re_err = f"{type(re_exc).__name__}: {re_exc}"
                    print(f"⚠️ [vibe-ths-linker] 重连失败：{re_exc}")
                    self._report_status("error", f"重连失败：{re_err}", str(re_exc))
                    time.sleep(3.0)
            time.sleep(0.15)

    def _instance_payload(self) -> dict[str, str]:
        body: dict[str, str] = {"ths_dir": self._ths_dir}
        if self._instance_title:
            body["title"] = self._instance_title
        pid = self._instance.get("id") or self._instance.get("pid")
        if pid:
            body["pid"] = str(pid)
        return body

    def _apply_stock_from_get(self, msg: dict) -> None:
        stocks = msg.get("stocks") or {}
        info = stocks.get(self._ths_dir) or {}
        code = str(info.get("code") or "").strip()
        if not code:
            return
        self._on_stock_changed(
            code,
            source="get",
            symbol=str(info.get("symbol") or "").strip() or None,
            market_id=str(info.get("market_id") or "").strip() or None,
        )

    def _on_ws_push(self, msg: dict) -> None:
        if not self._ready:
            self._pending_pushes.append(msg)
            return
        self._dispatch_push(msg)

    def _flush_pending_pushes(self) -> None:
        pending = self._pending_pushes
        self._pending_pushes = []
        for msg in pending:
            self._dispatch_push(msg)

    def _dispatch_push(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "stock_code":
            self._on_stock_push(msg)
        elif mtype == "trade":
            self._on_trade_push(msg)

    def _on_stock_push(self, msg: dict) -> None:
        ths_dir = str(msg.get("ths_dir") or "").strip()
        if ths_dir and ths_dir != self._ths_dir:
            return
        code = str(msg.get("code") or "").strip()
        if code:
            self._on_stock_changed(
                code,
                source="push",
                symbol=str(msg.get("symbol") or "").strip() or None,
                market_id=str(msg.get("market_id") or "").strip() or None,
            )

    def _on_trade_push(self, msg: dict) -> None:
        ths_dir = str(msg.get("ths_dir") or "").strip()
        if ths_dir and ths_dir != self._ths_dir:
            return
        snapshot = msg.get("snapshot")
        if snapshot is None:
            holdings = msg.get("holdings")
            if not isinstance(holdings, list):
                return
            snapshot = {"holdings": holdings}
        if not isinstance(snapshot, dict):
            return
        try:
            self._apply_portfolio_snapshot(snapshot)
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            print(f"⚠️ [vibe-ths-linker] 持仓推送同步失败：{err}")
            traceback.print_exc()
            self._report_status("warn", f"持仓推送同步失败：{err}", traceback.format_exc())

    def _on_stock_changed(
        self,
        code: str,
        *,
        source: str,
        symbol: str | None = None,
        market_id: str | None = None,
    ) -> None:
        if code == self._last_stock_code:
            return
        prev = self._last_stock_code
        self._last_stock_code = code
        payload: dict[str, Any] = {
            "code": code,
            "ths_dir": self._ths_dir,
            "instance_id": self._instance.get("id") if self._instance else None,
            "source": source,
            "prev": prev,
        }
        if symbol:
            payload["symbol"] = symbol
        if market_id:
            payload["market_id"] = market_id
        try:
            result = self._reg.report_current_stock(payload)
            if result.ok and result.detail != "unchanged":
                print(f"[vibe-ths-linker] 股票切换 {prev or '—'} → {code} ({source})")
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ [vibe-ths-linker] 上报当前股票失败：{exc}")

    def _sync_watchlist(self) -> None:
        _ensure_vr_path()
        import watchlist as wl  # noqa: PLC0415

        resp = self._client.request(
            {"type": "self_stock", "action": "list", **self._instance_payload()},
            expect_type="self_stock_result",
        )
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error") or "自选股列表读取失败")
        items = resp.get("items") or []
        codes: list[str] = []
        seen: set[str] = set()
        for it in items:
            code = str(it.get("code") or "").strip()
            if len(code) != 6 or not code.isdigit() or code in seen:
                continue
            seen.add(code)
            codes.append(code)
        source = "插件：vibe-ths-linker（同花顺）"
        sig = tuple(codes)
        if sig == self._last_watchlist:
            return
        if sig == tuple(wl.get_codes()):
            self._last_watchlist = sig
            return
        result = self._reg.import_watchlist({
            "replace": True,
            "source": source,
            "codes": codes,
        })
        if result.ok:
            self._last_watchlist = sig
            print(f"[vibe-ths-linker] 自选股已更新 {len(codes)} 只（来源：{source}）")

    def _apply_portfolio_snapshot(self, snapshot: dict) -> None:
        _ensure_vr_path()
        import portfolio as pf  # noqa: PLC0415

        holdings = [
            {"code": h["code"], "shares": h["shares"], "cost": h["cost"]}
            for h in (snapshot.get("holdings") or [])
            if isinstance(h, dict) and h.get("code")
        ]
        norm_holdings = _normalize_holdings(holdings)
        equity = snapshot.get("equity")
        fields = _account_fields_from_snapshot(snapshot)
        sig = _json_sig({
            "holdings": norm_holdings,
            "equity": equity,
            "account_fields": fields,
        })
        if sig == self._last_portfolio_sig:
            return
        current = pf.get_portfolio()
        cur_holdings = _normalize_holdings(current.get("holdings"))
        from duanxian import trade_store as ts  # noqa: PLC0415

        account = ts.load_account()
        cur_sig = _json_sig({
            "holdings": cur_holdings,
            "equity": account.get("equity"),
            "account_fields": account.get("account_fields") or {},
        })
        if sig == cur_sig:
            self._last_portfolio_sig = sig
            return
        payload: dict[str, Any] = {"replace": True, "holdings": holdings}
        if equity is not None:
            payload["equity"] = equity
        if fields:
            payload["account_fields"] = fields
            payload["note"] = ts.format_account_summary(fields)
        result = self._reg.import_portfolio(payload)
        if result.ok:
            self._last_portfolio_sig = sig
            print(f"[vibe-ths-linker] 持仓已更新 {len(norm_holdings)} 笔（trade push）")

    def _build_vibe_risk(self) -> dict[str, Any] | None:
        from duanxian import trade_calendar, trade_store as ts  # noqa: PLC0415

        date = trade_calendar.latest_session()
        if not date:
            from duanxian.util import china_today

            date = china_today()
        budget = ts.get_or_compute(date)
        if not budget.get("available"):
            return None
        cap_total = budget.get("cap_total")
        cap_single = budget.get("cap_single")
        if cap_total is None or cap_single is None:
            return None
        account = ts.load_account()
        consts = account.get("constants") or {}
        phase = str(budget.get("phase") or "")
        forbid = [str(x) for x in (budget.get("forbid") or []) if str(x).strip()]
        allow = [str(x) for x in (budget.get("allow") or []) if str(x).strip()]
        prompt_lines = [
            ln.strip()
            for ln in str(budget.get("prompt") or "").splitlines()
            if ln.strip()
        ]
        market_prompts: list[str] = []
        if phase:
            market_prompts.append(f"档位：{phase}")
        if prompt_lines:
            market_prompts.extend(prompt_lines[:8])
        else:
            market_prompts.extend(forbid[:8])
        stock_buy_prompts = list(prompt_lines[:6] if prompt_lines else forbid[:6])
        if not prompt_lines and allow:
            stock_buy_prompts.append("允许：" + "、".join(allow[:4]))
        sell_prompts: list[str] = []
        if phase in ("过热防守", "退潮杀伤", "高潮拥挤"):
            sell_prompts.append(f"{phase}：注意减仓")
        daily_limit = consts.get("daily_loss_limit")
        if daily_limit is not None:
            market_prompts.append(f"日亏上限 {float(daily_limit) * 100:.1f}%")
        return {
            "enabled": True,
            "total_position_limit_pct": round(float(cap_total) * 100, 2),
            "single_stock_limit_pct": round(float(cap_single) * 100, 2),
            "market_prompts": market_prompts,
            "stock_buy_prompts": stock_buy_prompts,
            "sell_prompts": sell_prompts,
        }

    def _sync_risk_control(self) -> None:
        desired = self._build_vibe_risk()
        if not desired:
            return
        sig = _json_sig(desired)
        if sig == self._last_risk_sig:
            return
        current_resp = self._client.request(
            {"type": "risk_control", "action": "get", **self._instance_payload()},
            expect_type="risk_control_result",
        )
        if not current_resp.get("ok"):
            raise RuntimeError(current_resp.get("error") or "风控配置读取失败")
        settings = current_resp.get("settings") or {}
        cur_compare = {
            "enabled": settings.get("enabled"),
            "total_position_limit_pct": settings.get("total_position_limit_pct"),
            "single_stock_limit_pct": settings.get("single_stock_limit_pct"),
            "market_prompts": list(settings.get("market_prompts") or []),
            "stock_buy_prompts": list(settings.get("stock_buy_prompts") or []),
            "sell_prompts": list(settings.get("sell_prompts") or []),
        }
        if _json_sig(cur_compare) == sig:
            self._last_risk_sig = sig
            return
        update_body = {"type": "risk_control", "action": "update", **self._instance_payload(), **desired}
        resp = self._client.request(update_body, expect_type="risk_control_result")
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error") or "风控配置同步失败")
        self._last_risk_sig = sig
        print("[vibe-ths-linker] 风控配置已同步至 ths-linker")


_BRIDGE: ThsLinkerBridge | None = None


def on_enable(reg: HookRegistry) -> None:
    global _BRIDGE
    if _BRIDGE is not None:
        return
    plugin_id = reg.plugin_id or ""
    bridge = ThsLinkerBridge(reg, plugin_id)
    try:
        bridge.start()
    except Exception:
        bridge.stop()
        raise
    _BRIDGE = bridge


def on_disable() -> None:
    global _BRIDGE
    if _BRIDGE is None:
        return
    _BRIDGE.stop()
    _BRIDGE = None


PACK = HookPack(
    name="vibe-ths-linker",
    version="1.0.0",
    schema_bundle="vibe-ths-linker/1.0.0",
    on_enable=on_enable,
    on_disable=on_disable,
    enable_review_saved=False,
)
