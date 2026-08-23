"""vibe ↔ ths-linker 桥接插件 —— 经 WebSocket 联动同花顺实例。

依赖：pip install -r plugins/vibe-ths-linker/requirements.txt
环境变量：
  THS_LINKER_WS_URL  默认 ws://127.0.0.1:8765
"""

from __future__ import annotations

import json
import os
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
_STATE_DIR = Path.home() / ".vibe-astock"
_STATE_FILE = _STATE_DIR / "ths-linker-current.json"

_STOCK_INTERVAL = 1.0
_SYNC_INTERVAL = 60.0
_WS_TIMEOUT = 20.0


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
    """ths-linker WebSocket 同步客户端（单连接、请求-响应配对）。"""

    def __init__(self, url: str) -> None:
        self._url = url
        self._ws: websocket.WebSocket | None = None
        self._lock = threading.Lock()
        self._on_push: Callable[[dict], None] | None = None

    def set_push_handler(self, handler: Callable[[dict], None] | None) -> None:
        self._on_push = handler

    def connect(self) -> None:
        self.close()
        ws = websocket.create_connection(self._url, timeout=_WS_TIMEOUT)
        ws.settimeout(2.0)
        self._ws = ws

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None

    def request(
        self,
        payload: dict,
        *,
        expect_type: str | None = None,
        expect_types: tuple[str, ...] | None = None,
    ) -> dict:
        allowed = set(expect_types or ([] if expect_type is None else [expect_type]))
        with self._lock:
            if self._ws is None:
                self.connect()
            assert self._ws is not None
            action = payload.get("action")
            self._ws.send(json.dumps(payload, ensure_ascii=False))
            deadline = time.monotonic() + _WS_TIMEOUT
            while time.monotonic() < deadline:
                try:
                    raw = self._ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                msg = json.loads(raw)
                mtype = msg.get("type")
                if mtype == "stock_code" and msg.get("action") == "push":
                    if self._on_push:
                        self._on_push(msg)
                    continue
                if allowed and mtype not in allowed:
                    continue
                if action and msg.get("action") and msg.get("action") != action:
                    continue
                return msg
            raise TimeoutError(f"等待 {allowed or '响应'} 超时：{payload}")

    def drain_initial(self) -> dict | None:
        """连接后读取服务端主动推送的 stock_code get 快照。"""
        with self._lock:
            if self._ws is None:
                return None
            try:
                raw = self._ws.recv()
                msg = json.loads(raw)
                if msg.get("type") == "stock_code" and msg.get("action") == "get":
                    return msg
            except Exception:  # noqa: BLE001
                return None
        return None


class ThsLinkerBridge:
    def __init__(self, reg: HookRegistry, plugin_id: str) -> None:
        self._reg = reg
        self._plugin_id = plugin_id
        self._client = ThsLinkerWsClient(_WS_URL)
        self._client.set_push_handler(self._on_stock_push)
        self._instance: dict | None = None
        self._ths_dir = ""
        self._instance_title = ""
        self._last_stock_code: str | None = None
        self._last_watchlist: tuple[str, ...] | None = None
        self._last_portfolio_sig: str | None = None
        self._last_risk_sig: str | None = None
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
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run_loop, name="ths-linker-bridge", daemon=True)
        self._thread.start()
        detail = f"pid={self._instance.get('id')} ths_dir={self._ths_dir}"
        print(f"[vibe-ths-linker] 已绑定实例 {detail}")
        reg.report_status("ok", "已连接 ths-linker", detail)

    def _report_status(self, level: str, message: str, detail: str | None = None) -> None:
        from duanxian import plugin_status as ps

        if self._plugin_id:
            ps.set_status(self._plugin_id, level, message, detail)

    def _run_loop(self) -> None:
        last_stock = 0.0
        last_sync = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                if now - last_stock >= _STOCK_INTERVAL:
                    self._poll_stock_code()
                    last_stock = now
                if now - last_sync >= _SYNC_INTERVAL:
                    self._sync_watchlist()
                    self._sync_portfolio()
                    self._sync_risk_control()
                    last_sync = now
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                print(f"⚠️ [vibe-ths-linker] 同步异常：{err}")
                traceback.print_exc()
                self._report_status("warn", f"同步异常：{err}", traceback.format_exc())
                try:
                    self._client.connect()
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

    def _poll_stock_code(self) -> None:
        resp = self._client.request(
            {"type": "stock_code", "action": "get"},
            expect_types=("stock_code", "stock_code_result"),
        )
        self._apply_stock_from_get(resp)

    def _apply_stock_from_get(self, msg: dict) -> None:
        stocks = msg.get("stocks") or {}
        info = stocks.get(self._ths_dir) or {}
        code = str(info.get("code") or "").strip()
        if not code:
            return
        self._on_stock_changed(code, source="poll")

    def _on_stock_push(self, msg: dict) -> None:
        ths_dir = str(msg.get("ths_dir") or "").strip()
        if ths_dir and ths_dir != self._ths_dir:
            return
        code = str(msg.get("code") or "").strip()
        if code:
            self._on_stock_changed(code, source="push")

    def _on_stock_changed(self, code: str, *, source: str) -> None:
        if code == self._last_stock_code:
            return
        prev = self._last_stock_code
        self._last_stock_code = code
        payload = {
            "code": code,
            "ths_dir": self._ths_dir,
            "instance_id": self._instance.get("id") if self._instance else None,
            "source": source,
            "prev": prev,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            _STATE_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"⚠️ [vibe-ths-linker] 写入状态文件失败：{exc}")
        print(f"[vibe-ths-linker] 股票切换 {prev or '—'} → {code} ({source})")

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
        codes = tuple(sorted({str(it.get("code") or "").strip() for it in items if it.get("code")}))
        if codes == self._last_watchlist:
            return
        current = tuple(sorted(wl.get_codes()))
        if codes == current:
            self._last_watchlist = codes
            return
        result = self._reg.import_watchlist({"replace": True, "codes": list(codes)})
        if result.ok:
            self._last_watchlist = codes
            print(f"[vibe-ths-linker] 自选股已更新 {len(codes)} 只")

    def _sync_portfolio(self) -> None:
        _ensure_vr_path()
        import portfolio as pf  # noqa: PLC0415

        resp = self._client.request(
            {"type": "trade", "action": "snapshot", **self._instance_payload()},
            expect_type="trade_result",
        )
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error") or "trade snapshot 读取失败")
        snapshot = resp.get("snapshot")
        if not isinstance(snapshot, dict):
            raise RuntimeError("trade snapshot 响应缺少 snapshot 字段")
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
            print(f"[vibe-ths-linker] 持仓已更新 {len(norm_holdings)} 笔")

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
        market_prompts: list[str] = []
        if phase:
            market_prompts.append(f"档位：{phase}")
        market_prompts.extend(forbid[:8])
        stock_buy_prompts = list(forbid[:6])
        if allow:
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


def on_register(reg: HookRegistry) -> None:
    global _BRIDGE
    plugin_id = reg.plugin_id or ""
    _BRIDGE = ThsLinkerBridge(reg, plugin_id)
    _BRIDGE.start()


PACK = HookPack(
    name="vibe-ths-linker",
    version="1.0.0",
    schema_bundle="vibe-ths-linker/1.0.0",
    on_register=on_register,
    enable_review_saved=False,
)
