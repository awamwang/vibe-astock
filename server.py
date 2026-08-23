"""短线复盘 Web 后端 —— FastAPI 包住复盘图 + 缓存 + 静态前端"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import threading
import time
import uuid
from typing import Optional
from urllib.parse import urlparse

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from duanxian import (
    live_emotion, mood_block, overseas, preflight, reflection, review_store, screenshot_parse,
    short_board, trade_calendar, trade_budget, trade_store,
)
from duanxian.review_store import md_to_html as _md_to_html, strip_prefix as _strip_prefix
from duanxian.config import make_llm
from duanxian.review_graph import build_review_graph
from duanxian.roles import ROLES
from main import initial_state
from duanxian.util import (
    china_now, china_today, is_a_share_closed, is_degraded_report, is_weekend,
    safe_join, strip_model_noise, validate_trade_date,
)
from duanxian.prompts import PACK

SCHEMA_VERSION = 1
_HERE = os.path.dirname(os.path.abspath(__file__))
# React 构建产物：存在就优先服务它，单端口即可访问全部界面，不必另起 vite dev。
# 构建：cd frontend && npm run build
_DIST = os.path.join(_HERE, "frontend", "dist")
_REVIEW_DIR = os.path.expanduser("~/.duanxian-agents/reviews")
_WK_DIR = os.path.expanduser("~/.duanxian-agents/weekly")
os.makedirs(_REVIEW_DIR, exist_ok=True)
os.makedirs(_WK_DIR, exist_ok=True)
# 允许写操作（POST/DELETE）的 Host。默认只认本机；挂到域名下访问时，用
# `VIBE_ALLOW_HOSTS="myhost,www.myhost"`（逗号分隔）把域名加进来，否则写操作会 403。
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"} | {
    h.strip() for h in os.environ.get("VIBE_ALLOW_HOSTS", "").split(",") if h.strip()
}

app = FastAPI(title="短线每日复盘")

# ---------------------------------------------------------------- 并入 VR 后端
# 盘面数据 / 首板分析 / 盯盘 / 持仓股 / 自选股 / 个股数据 / 资讯雷达 这几个分栏的
# 后端放在 `vr/`，它的路由在这里并到本 app 上，一个进程一个端口即可访问全部界面。
# `vr/` 原样来自开源的 Vibe-Research，日后拉更新就是一次纯拷贝。改成包内相对
# import 会让每次同步都变成手工 merge。


def _alert(msg: str) -> None:
    """必达的告警输出"""
    import sys

    print(msg, file=sys.stderr, flush=True)


_VR_PATH_RES: list[re.Pattern] = []


def _merge_vr_routes() -> int:
    """把 `vr/` 的路由并进本 app。返回并入条数；失败不影响本仓库自有功能。"""
    import sys

    vr_dir = os.path.join(_HERE, "vr")
    if not os.path.isdir(vr_dir):
        return 0
    if vr_dir not in sys.path:
        sys.path.insert(0, vr_dir)   # 放最前，确保 `import astock` 等解析到 vr/ 内
    try:
        import app as vr_app  # noqa: PLC0415  vr/app.py（不是本仓库的模块）

        before = len(app.router.routes)
        # 只拿 /api/* 的；VR 没有非 /api 路由，这层过滤是为了防它日后加了根路由
        # 把我们的 SPA fallback 顶掉
        for r in vr_app.app.router.routes:
            path = getattr(r, "path", "")
            if not path.startswith("/api/"):
                continue
            app.router.routes.append(r)
            # 记下路径模板 → 正则（`{rid}` 这类参数换成"一段非斜杠"），
            # 供下面那道补偿闸判断"这个请求是不是打在 VR 路由上"
            _VR_PATH_RES.append(re.compile(
                "^" + re.sub(r"\{[^}]+\}", r"[^/]+", re.escape(path)
                             .replace(r"\{", "{").replace(r"\}", "}")) + "$"))
        return len(app.router.routes) - before
    except Exception as exc:  # noqa: BLE001  VR 挂了不该让复盘/交易日志也用不了
        _alert(f"⚠️ VR 后端并入失败（那 7 个分栏会不可用）：{type(exc).__name__}: {exc}")
        return 0


def _guard_vr_userdata() -> None:
    """启动时给 VR 的**不可再生用户数据**留一份备份"""
    import shutil

    vr_home = os.path.expanduser("~/.vibe-research")
    pf = os.path.join(vr_home, "portfolio.json")
    if not os.path.isfile(pf):
        return
    try:
        with open(pf, encoding="utf-8") as fh:
            json.load(fh)
    except Exception as exc:  # noqa: BLE001
        # 损坏：把原始字节另存（带时间戳，不覆盖之前的），并大声说出来
        stamp = china_now().strftime("%Y%m%d-%H%M%S")
        dst = os.path.join(vr_home, f"portfolio.corrupt-{stamp}.json")
        try:
            shutil.copy2(pf, dst)
        except Exception:  # noqa: BLE001
            dst = "（另存也失败了）"
        _alert(f"🔴 VR 持仓文件无法解析（{type(exc).__name__}）！"
               "vr/portfolio.py 会把它当成空持仓，并在 30 分钟内写回覆盖掉。")
        _alert(f"   原始字节已另存：{dst}")
        _alert(f"   历史可解析备份：{vr_home}/portfolio.good-*.json（挑最近的非空那份恢复）")
        return
    try:
        with open(pf, encoding="utf-8") as fh:
            cur = json.load(fh)
        holdings = (cur or {}).get("holdings") or []
        stamp = china_now().strftime("%Y%m%d")
        dst = os.path.join(vr_home, f"portfolio.good-{stamp}.json")
        if not holdings:
            # 空持仓 + 已经存在任何非空备份 → 这大概率是"损坏后被写成空"的产物，别覆盖
            import glob

            for old_bak in glob.glob(os.path.join(vr_home, "portfolio.good-*.json")):
                try:
                    with open(old_bak, encoding="utf-8") as fh:
                        if (json.load(fh) or {}).get("holdings"):
                            return   # 有非空的历史备份在，什么都不做
                except Exception:  # noqa: BLE001
                    continue
        shutil.copy2(pf, dst)
    except Exception as exc:  # noqa: BLE001  备份失败要出声，但不阻断启动
        _alert(f"⚠️ VR 持仓备份失败（{type(exc).__name__}）：{vr_home}/portfolio.good-*.json")


_SAFE_CLI_KINDS = frozenset({"claude"})


def _opted_in_clis() -> frozenset[str]:
    """`VIBE_ALLOW_UNSAFE_CLI=qwen,deepseek` —— 运行服务的人**显式**放开的"""
    raw = os.environ.get("VIBE_ALLOW_UNSAFE_CLI", "")
    return frozenset(k.strip() for k in raw.split(",") if k.strip())


_ALLOWED_CLI_KINDS = _SAFE_CLI_KINDS | _opted_in_clis()

# 已知并有意禁掉的。只用于区分「预期内」和「上游新来的」，**不参与放行判断**
# —— 放行只看白名单，这个集合少写了什么也不会让谁被放进来。
_KNOWN_UNSAFE_CLIS = frozenset({"qwen", "deepseek", "codex", "opencode", "cursor", "kimi"})

# 摘除前的完整 CLI 定义快照 —— 给 `/api/cli/available` 报"这个 kind 装没装"用。
# 摘掉之后 `detect_cli()` 一律返回 None，分不清"没装"和"被禁"，而这两件事
# 对用户是完全不同的信息（一个去装、一个别想了）。
_ALL_CLI_BINS: dict[str, list[str]] = {}

from duanxian.cli_llm import _BINS_ATTR_NAME as _BINS_ATTR  # 单一来源，见那边注释


def _cli_runtime_modules() -> list:
    """所有**已加载的** cli_runtime 模块对象"""
    mods = [m for name, m in list(sys.modules.items())
            if m is not None and (name == "cli_runtime" or name.endswith(".cli_runtime"))
            and hasattr(m, "_CLI_DEFS")]
    if mods:
        return mods
    try:
        import cli_runtime as _cr  # noqa: PLC0415
    except Exception:              # noqa: BLE001  这一版可能根本没带这个文件
        return []
    return [_cr] if hasattr(_cr, "_CLI_DEFS") else []


def _disable_unsafe_clis() -> list[str]:
    """把不在白名单里的 CLI 从**每一份** CLI 运行时字典摘掉，返回实际摘掉的。"""
    mods = _cli_runtime_modules()
    if not mods:
        _alert("🔴 找不到 cli_runtime 模块 ——「接入AI」的自动批准 CLI 可能仍可用，请检查")
        return []

    for mod in mods:
        if not hasattr(mod, _BINS_ATTR):
            setattr(mod, _BINS_ATTR,
                    {k: list(d.get("bins") or []) for k, d in mod._CLI_DEFS.items()})
        _ALL_CLI_BINS.update(getattr(mod, _BINS_ATTR))

    removed: set[str] = set()
    for mod in mods:
        for k in [k for k in list(mod._CLI_DEFS) if k not in _ALLOWED_CLI_KINDS]:
            mod._CLI_DEFS.pop(k, None)
            removed.add(k)

    live = sys.modules.get("app")
    if live is None or not hasattr(live, "cli_runtime"):
        _alert("⚠️ 无法校验 CLI 禁用是否生效：没找到已加载的 VR app 模块")
    else:
        leftover = sorted(set(live.cli_runtime._CLI_DEFS) - _ALLOWED_CLI_KINDS)
        if leftover:
            _alert(f"🔴 禁用没生效！/api/chat 实际用的运行时里仍有 {leftover} —— 存在第三份 cli_runtime？")

    # 上游新增的（不在我们已知清单里的）要报警 —— 白名单挡住了它，但人得知道
    unknown = sorted(removed - _KNOWN_UNSAFE_CLIS)
    if unknown:
        _alert(f"⚠️ vr/ 上游新增了 CLI {unknown}，已按白名单摘掉。确认安全后再加进 _ALLOWED_CLI_KINDS")
    return sorted(removed)


def _add_vr_to_path() -> None:
    """只把 `vr/` 放进 sys.path，不挂它的路由"""
    import sys
    vr_dir = os.path.join(_HERE, "vr")
    if os.path.isdir(vr_dir) and vr_dir not in sys.path:
        sys.path.insert(0, vr_dir)


_VR_ROUTES = _merge_vr_routes()
def _pin_pool_to_settled_session() -> int:
    """把「涨停池」的可见范围钉在**已经收盘**的交易日上。返回 1 = 已生效。

    `vr/` 的首板分析、短线情绪都是"从今天往前回溯，第一天有池子就用它"。
    东财在**盘中**就发布当日池子，于是 09:35 打开看到的是「今天才 18 家涨停」
    这种半成品，而复盘看板是上一场（07-29 的 81 家）—— 同一个产品两个日期，
    而且每刷一次数字都变，最容易让人整块不信。

    复盘系统不做当日动态分析。所以这里不去改 `vr/`（要保持能同步上游），
    而是给它的取数口包一层：**未收盘的交易日，涨停池视为"还没有"**，
    它的回溯逻辑就自然落到上一场，一行都不用动它。

    影响面只在 `vr/` 那几个走涨停池的块；复盘链路走的是
    `duanxian/fetchers.py`（akshare），不受这层影响。
    """
    live = sys.modules.get("astock")
    if live is None or not hasattr(live, "em_zt_topic_pool"):
        _alert("⚠️ 没能钉住涨停池日期：找不到已加载的 vr astock —— "
               "首板/短线情绪可能显示盘中半成品")
        return 0
    if getattr(live, "_pool_pinned", False):
        return 1                                   # 幂等：重复调用无害

    orig = live.em_zt_topic_pool

    def guarded(kind, date, sort, *a, **kw):
        ymd = str(date)
        if len(ymd) == 8 and ymd.isdigit():
            iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
            if not trade_calendar.is_settled(iso):
                return []                          # 还没收盘 → 当作还没有池子
        return orig(kind, date, sort, *a, **kw)

    live.em_zt_topic_pool = guarded
    live._pool_pinned = True
    # 留一个未加锁的原函数出口：盘面数据页要显示**今日实时**的打板情绪，
    # 而这道锁是给复盘类块用的。锁是钝器，需要今天数据的地方走这个口子。
    live._pool_unpinned = orig
    return 1


_POOL_PINNED = _pin_pool_to_settled_session()
_guard_vr_userdata()


def _bootstrap_watchlist() -> None:
    """启动时把磁盘自选股灌进盯盘池（插件 / API 写入的列表）。"""
    _add_vr_to_path()
    try:
        import watchlist as wl  # noqa: PLC0415
        import watchtower as wt  # noqa: PLC0415

        codes = wl.get_codes()
        if codes:
            wt.set_watch(codes)
    except Exception as exc:  # noqa: BLE001
        _alert(f"⚠️ 自选股恢复失败：{type(exc).__name__}: {exc}")


_bootstrap_watchlist()
_DISABLED_CLIS = _disable_unsafe_clis()

_VR_API_KEY = os.environ.get("VR_API_KEY", "").strip()

# 需要 Origin 校验的方法。我们自有的写操作都在 handler 里手工调 `_origin_ok`，
# 但 VR 的 handler **我们不改**（要保持上游原样）→ 只能在 middleware 层补。
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _is_vr_path(path: str) -> bool:
    return any(rx.match(path) for rx in _VR_PATH_RES)


@app.middleware("http")
async def _vr_guard(request: Request, call_next):
    """给并进来的 VR 路由补两道闸"""
    if _is_vr_path(request.url.path):
        if (_VR_API_KEY and request.method != "OPTIONS"
                and request.url.path != "/api/health"
                and request.headers.get("authorization", "") != f"Bearer {_VR_API_KEY}"):
            return JSONResponse({"error": "未授权：缺少或错误的 VR_API_KEY"}, status_code=401)
        if request.method in _MUTATING and not _origin_ok(request):
            return JSONResponse({"error": "非法来源"}, status_code=403)
    return await call_next(request)

_lock = threading.Lock()
_job = {
    "running": False, "job_id": None, "date": None, "error": None,
    "started": None, "elapsed": 0, "finished_at": None,
}

_JOB_TIMEOUT = 15 * 60


def _job_stuck(job: dict, limit: int) -> bool:
    """任务是否已超时卡死 —— 卡死的任务不该再挡住新任务。"""
    return bool(job.get("running") and job.get("started")
                and time.time() - job["started"] > limit)


def _atomic_write(path: str, payload: dict) -> None:
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)  # 原子替换，读方永远看到完整文件


def _capture_theme_reasons() -> None:
    """囤当天的题材串（1 次问财请求）。 只能查最近交易日，过期不候"""
    try:
        from duanxian import theme_tree

        r = theme_tree.capture()
        if not r.get("ok"):
            print(f"⚠️ 题材串囤积失败（{r.get('date')}）：{r.get('reason')}")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 题材串囤积异常：{type(exc).__name__}: {exc}")
def _run_review(date: str, job_id: str) -> None:
    try:
        # 先体检输入 —— 核心数据取不到就别跑。喂空数据进去，模型会硬凑出
        # 看着可信的结论（实测点到一只当天 -6.81% 的票当"主线代表"）。
        pre = preflight.check(date)
        if not pre["ok"]:
            raise RuntimeError(preflight.refuse_reason(pre, date))

        graph = build_review_graph()
        final = graph.invoke(initial_state(date), {"recursion_limit": 50})
        reflection.auto_evaluate_prior(date)  # 先回评上期预测（其次日=今天，数据已出）
        # 体检发现的非核心缺失要如实落进 warnings，界面才会显示「⚠ 部分数据降级」
        payload = review_store.serialize(final, date, pre["warnings"])
        res = review_store.save(payload, date)
        if not res.written:
            # 产物不可用 → 必须让用户看见，不能"任务成功但内容是空的"
            raise RuntimeError(res.reason)
        _capture_theme_reasons()     # 题材串同理（问财只给最近交易日）
        # 仓位预算：与复盘同源读数，但写入 trade/，绝不进 reviews JSON
        budget_env = None
        try:
            budget_env = trade_store.refresh(date, emit_hooks=False)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ 仓位预算写入失败（{date}）：{type(exc).__name__}: {exc}")
        try:
            from duanxian import hooks

            hooks.RUNNER.emit_after_review(date, payload, budget_env)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ 复盘钩子派发失败（{date}）：{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        with _lock:
            if _job["job_id"] == job_id:
                _job["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with _lock:
            if _job["job_id"] == job_id:  # 只结束属于自己的任务（#5）
                _job["running"] = False
                if _job["started"]:
                    _job["elapsed"] = int(time.time() - _job["started"])  # 收尾定格 elapsed（#17）
                _job["finished_at"] = china_now().strftime("%Y-%m-%d %H:%M:%S") + " CST"


def _origin_ok(request: Request) -> bool:
    """只允许本机来源触发昂贵任务，挡掉恶意网页的跨站 POST（#22）。"""
    ref = request.headers.get("origin") or request.headers.get("referer") or ""
    if not ref:
        return True  # 无 Origin（如 curl 本地调用）放行
    return (urlparse(ref).hostname or "") in _ALLOWED_HOSTS


def _force_flag(request: Request) -> bool:
    """`?force=1` —— 已复盘过还要重跑。只认 POST 上的查询参数（本路由本身是 POST）。"""
    return str(request.query_params.get("force", "")).strip().lower() in ("1", "true", "yes")


@app.post("/api/review/run")
def api_run(request: Request, date: str | None = None):
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    try:
        explicit = bool(date)
        if not explicit:
            # 复盘的对象只能是**已经收盘的那一场**。原来这里在工作日直接用 today，
            # 于是盘前点一下就为「还没开盘的今天」开跑：涨停池 / 龙虎榜 / 资金流全空，
            # 四个分析师如实说"数据缺失"，裁判却照样端出三个方向 + 点名个股
            # （实测点到一只当天 -6.81% 的票当"主线代表"）。
            # 复盘系统不做当日动态分析 —— 没收盘就还是上一场那份。
            date = trade_calendar.latest_session() or china_today()
        date = validate_trade_date(date)  # #1
        if is_weekend(date):
            return JSONResponse({"error": f"{date} 为周末非交易日"}, status_code=400)
        if not trade_calendar.is_settled(date):
            latest = trade_calendar.latest_session()
            return JSONResponse(
                {"error": f"{date} 还没收盘，复盘要用当天的收盘数据",
                 "suggest_date": latest,
                 "hint": f"最近已收盘的是 {latest}" if latest else None},
                status_code=409)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    # 那一场已经复盘过就别重跑 —— 直接告诉前端去看那天的页面。
    # 想重跑：带 force=1（改了口径/修了 bug 时才需要）。
    if not _force_flag(request) and review_store.usable(review_store.load(date)):
        return {"running": False, "date": date, "already_done": True,
                "message": f"{date} 已复盘"}

    with _lock:  # 原子 check-then-act（#5）
        if _job["running"] and not _job_stuck(_job, _JOB_TIMEOUT):
            return {"running": True, "date": _job["date"]}
        if _job["running"]:   # 卡死的旧任务：让位，并把原因如实写进 error
            _job["error"] = f"上一个任务（{_job.get('date')}）超过 {_JOB_TIMEOUT // 60} 分钟无响应，已判为卡死"
        job_id = uuid.uuid4().hex
        _job.update(running=True, job_id=job_id, date=date, error=None,
                    started=time.time(), elapsed=0, finished_at=None)
    threading.Thread(target=_run_review, args=(date, job_id), daemon=True).start()
    return {"running": True, "date": date, "job_id": job_id}


@app.get("/api/cli/available")
def api_cli_available():
    """哪些订阅 CLI 真的能用 —— **服务端是唯一权威**，UI 照这个渲染"""
    live = sys.modules.get("app")
    find_bin = getattr(getattr(live, "cli_runtime", None), "_find_bin", None)

    out = []
    for kind, bins in sorted(_ALL_CLI_BINS.items()):
        allowed = kind in _ALLOWED_CLI_KINDS
        # 被摘掉的 kind 用不了 `detect_cli`（它读的就是被摘空的那个 dict），
        # 所以直接拿摘除前记下的可执行名去找。
        installed = bool(find_bin and any(find_bin(b) for b in bins))
        out.append({
            "kind": kind,
            "allowed": allowed,
            "installed": installed,
            "reason": None if allowed else "自动批准 / 无沙箱，默认禁用",
        })
    return {
        "clis": out,
        # 放开的办法，直接告诉调用方，不用去翻文档
        "optInEnv": "VIBE_ALLOW_UNSAFE_CLI",
        "optedIn": sorted(_opted_in_clis()),
    }


@app.get("/api/review/status")
def api_status():
    with _lock:
        snap = dict(_job)
    if snap["running"] and snap["started"]:
        snap["elapsed"] = int(time.time() - snap["started"])
    snap.pop("started", None)
    return snap


@app.post("/api/review/evaluate")
def api_evaluate(request: Request, date: str):
    """手动评估某天的『明天关注点』命中情况（次一交易日实际涨跌）"""
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    try:
        date = validate_trade_date(date)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    res = reflection.evaluate(date)
    return res or {"error": "无可评估数据（缺该日预测，或次一交易日数据尚未出）"}


@app.get("/api/market/session")
def api_market_session():
    """此刻的「实时行情」到底属于哪一场。

    腾讯 / 东财的实时接口在盘前返回的是**上一场的收盘**，而且不带任何提示。
    界面若按「今天」给它们贴日期，盘前打开就会看到「今天 上证 +0.4%」——
    今天还没开盘，这个数是昨收。数字没错，标签错了，而这种错最容易让人
    对整块数据失去信任。所以把「哪一场」当成一等公民返回，由 UI 如实标注。
    """
    today = china_today()
    quotes_of = trade_calendar.quote_trade_day()
    is_today = bool(quotes_of) and quotes_of == today
    closed = is_a_share_closed()

    now = china_now()
    hhmm = now.hour * 60 + now.minute
    if not quotes_of:
        phase, label = "未知", "行情时间取不到"
    elif is_today and not closed and hhmm < 9 * 60 + 25:
        # 09:15-09:25 集合竞价：还没成交，指数等于昨收、涨跌幅是 0。
        # 不单独成一档的话，界面标"盘中·实时"而三个指数全是 0%，看着像数据坏了。
        phase, label = "集合竞价", "集合竞价 · 尚未成交"
    elif is_today and not closed:
        phase, label = "盘中", "盘中 · 实时"
    elif is_today:
        phase, label = "已收盘", f"{today} 收盘"
    elif is_weekend(today):
        phase, label = "非交易日", f"非交易日 · 显示 {quotes_of} 收盘"
    elif not closed:
        # 工作日、还没到收盘，而行情停在上一场 → 盘前（或今天是节假日）
        phase, label = "盘前", f"盘前 · 显示 {quotes_of} 收盘"
    else:
        phase, label = "非交易日", f"今日无成交 · 显示 {quotes_of} 收盘"

    return {"now": now.strftime("%Y-%m-%d %H:%M"), "today": today,
            "quotes_of": quotes_of, "is_today": is_today,
            "phase": phase, "label": label}


@app.get("/api/market/live-emotion")
def api_market_live_emotion():
    """今日**实时**打板情绪（盘面数据页用）。

    与 `vr/` 的 `/api/market/emotion` 并存：那条被锁在已收盘那一场（复盘口径），
    这条要的就是今天、随盘变化。两个块在界面上分别标清是哪一场。
    """
    return live_emotion.snapshot()


@app.get("/api/market/short-board")
def api_market_short_board():
    """短线盘面环境指标条（情绪温度 / 涨跌家数 / 涨跌停 / 成交额 / 资金等）。

    对齐 awam-stock Environment：选股宝 + 开盘啦 + 东财；量能两卡暂占位。
    """
    return short_board.snapshot()


@app.get("/api/market/mood-blocks")
def api_market_mood_blocks():
    """板块人气排名（开盘啦 RealRankingInfo ZSType=7）。

    对齐 awam-stock MoodBlockItem：人气 / 涨跌幅 / 主力净额 / 涨速；涨停家数合并 PlateAnalysis。
    """
    return mood_block.snapshot()


@app.get("/api/market/overseas")
def api_market_overseas():
    """隔夜外围：美港股指数 + 美股七姐妹，各自带交易日。

    与 `vr/` 的 `/api/global/indices` 并存 —— 那条不回行情时间，界面无法说清
    「这批数是哪一场的」（详见 duanxian/overseas.py 顶部）。
    """
    return overseas.overseas_snapshot()


@app.get("/api/review/dates")
def api_review_dates():
    """跑过复盘的交易日，新→旧。给看板的历史入口用。

    在此之前 `reviews/` 每天存一份、但只有 `latest.json` 有接口 ——
    对一个复盘产品来说「翻回上周三看看」是刚需，却没有入口。
    """
    return {"dates": review_store.dates()}


@app.get("/api/review/latest")
def api_latest(date: Optional[str] = None):
    """读复盘：不带 date 读最近一份；带 date 读那天的历史存档。"""
    if date:
        try:
            date = validate_trade_date(date)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    payload = review_store.load(date)   # 损坏/不存在都返回 None（不 500）
    if payload is None or not review_store.usable(payload):
        # 空对象 = 「这天没有」，前端据此显示"还没跑过"；带上 date 好让前端知道问的是哪天
        return JSONResponse({"requested_date": date} if date else {}, status_code=200)
    try:
        if date is None:
            payload["reflection"] = reflection.latest_reflection()
        payload["scoreboard"] = reflection.scoreboard()
    except Exception as exc:  # noqa: BLE001  战绩算不出来不该让整个复盘打不开
        print(f"⚠️ 战绩统计失败：{type(exc).__name__}: {exc}")
    return JSONResponse(payload)


# ==================== ③ 近 5 天热度 ====================
_wk_lock = threading.Lock()


def _wk_load():
    path = os.path.join(_WK_DIR, "latest.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return None


def _wk_fresh(cached: dict) -> bool:
    """缓存是否仍是最新已收盘交易日窗口（ #3）。判不了(网络失败)→按新鲜处理不硬刷"""
    from duanxian.weekly import LINEAGE_SCHEMA, WINDOW_DAYS_MAX

    days = cached.get("days") or []
    if not days:
        return False
    if cached.get("lineage_schema") != LINEAGE_SCHEMA:
        return False
    if int(cached.get("window_days") or 0) < WINDOW_DAYS_MAX:
        return False
    matrix = cached.get("theme_matrix") or {}
    by_day = matrix.get("by_day") if isinstance(matrix.get("by_day"), dict) else {}
    if not by_day:
        return False
    try:
        from duanxian.weekly import _last_trade_dates

        latest = _last_trade_dates(1)
        expected = latest[-1] if latest else None
    except Exception:  # noqa: BLE001
        expected = None
    return expected is None or days[-1].get("date") == expected


def _wk_good(w: dict) -> bool:
    """结果够格替换有效缓存吗（ #4：至少有一天真实取到数）"""
    return not w.get("error") and any((d.get("limit_up") is not None) for d in (w.get("days") or []))


@app.get("/api/weekly")
def api_weekly(request: Request, days: int = 10):
    """多日情绪 + 龙头谱系。`days` 控制展示窗口（7~15 个交易日）。"""
    return _weekly(force=False, days=days)


@app.post("/api/weekly/refresh")
def api_weekly_refresh(request: Request, days: int = 10):
    """强制重算多日情绪。写操作走 POST + Origin 校验（见 api_weekly 的说明）。"""
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    return _weekly(force=True, days=days)


def _weekly(force: bool, days: int = 10):
    """多日情绪的真正实现。`force` **只能由 POST 处理器传入**，不接受查询参数。"""
    from duanxian.weekly import build_weekly, ensure_theme_matrix, slice_weekly, WINDOW_DAYS_MAX, _clamp_window

    want = _clamp_window(days)

    def _respond(payload: dict) -> JSONResponse:
        enriched = ensure_theme_matrix(payload)
        return JSONResponse(slice_weekly(enriched, want))

    cached = _wk_load()
    if not force and cached and _wk_fresh(cached):
        return _respond(cached)

    if not _wk_lock.acquire(blocking=False):
        if cached:
            return _respond({**cached, "busy": True})
        return JSONResponse({"error": "正在计算中，请稍后重试", "busy": True}, status_code=409)
    try:
        cached2 = _wk_load()
        if not force and cached2 and _wk_fresh(cached2):
            return _respond(cached2)
        w = build_weekly(WINDOW_DAYS_MAX)
        w["generated_at"] = china_now().strftime("%Y-%m-%d %H:%M")
        days_list = w.get("days") or []
        w["last_trade_date"] = days_list[-1].get("date") if days_list else None
        if _wk_good(w):
            try:
                _atomic_write(safe_join(_WK_DIR, "latest.json"), w)
            except Exception:  # noqa: BLE001
                pass
            return _respond(w)
        if cached2 and (cached2.get("days")):
            stale = dict(cached2)
            stale["stale"] = True
            stale["warnings"] = (stale.get("warnings") or []) + ["刷新失败，展示上一份有效数据"]
            return _respond(stale)
        return _respond(w)
    finally:
        _wk_lock.release()


_chat_llm = None
_ROLE_MAP = {"user": "human", "assistant": "ai"}

# 对话体量上限。本机其它进程也能打这个口，不设限就能构造超长请求把 LLM 额度烧光。
_CHAT_MAX_MESSAGES = 40       # 超出部分只保留最近的（_chat 内还会再截到 12 轮）
_CHAT_MAX_CHARS_EACH = 4000
_CHAT_MAX_CHARS_TOTAL = 24000


def _sanitize_messages(msgs: object) -> tuple[list, Optional[str]]:
    """校验并裁剪对话消息。返回 (清洗后的消息, 错误信息)。"""
    if not isinstance(msgs, list) or not msgs:
        return [], "空消息"
    if len(msgs) > _CHAT_MAX_MESSAGES:
        msgs = msgs[-_CHAT_MAX_MESSAGES:]
    out, total = [], 0
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "user")
        if role not in _ROLE_MAP:
            return [], f"不支持的 role：{role!r}（只接受 user / assistant）"
        content = str(m.get("content", ""))[:_CHAT_MAX_CHARS_EACH]
        total += len(content)
        if total > _CHAT_MAX_CHARS_TOTAL:
            return [], "对话内容过长，请开新会话"
        out.append({"role": role, "content": content})
    return (out, None) if out else ([], "空消息")


def _chat_model():
    global _chat_llm
    if _chat_llm is None:
        _chat_llm = make_llm(deep=False)
    return _chat_llm


def _strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def _load_latest_json(dirpath: str) -> dict:
    path = os.path.join(dirpath, "latest.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return {}


def _review_context() -> str:
    d = _load_latest_json(_REVIEW_DIR)
    if not d:
        return "（暂无复盘数据，请先在复盘 Agent 生成一次复盘。）"
    parts = [f"复盘交易日 {d.get('target_date', '')}", f"【明天关注点】\n{d.get('focus_md', '')}"]
    if d.get("macro_sector"):
        parts.append(f"【大板块本周】\n{d['macro_sector']}")
    for a in d.get("analysts", []):
        parts.append(f"【{a.get('title', '')}】\n{_strip_html(a.get('html', ''))}")
    return "\n\n".join(parts)[:8000]
def _chat(context: str, role_desc: str, messages: list) -> dict:
    system = (
        f"你是{role_desc}。下面是刚才多 agent 产出的结论与数据，用户会就它追问或让你展开。\n"
        f"{PACK.chat_guidance}\n"
        "不要提及你自己的身份或模型名。\n\n" + context
    )
    try:
        chain = [("system", system)] + [
            (_ROLE_MAP.get(m["role"], "human"), m["content"])
            for m in messages[-12:]
        ]
        ans = _chat_model().invoke(chain).content
        return {"answer": strip_model_noise(ans)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


@app.post("/api/review/chat")
def api_review_chat(request: Request, body: dict = Body(...)):
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    msgs, err = _sanitize_messages(body.get("messages"))
    if err:
        return JSONResponse({"error": err}, status_code=400)
    return _chat(_review_context(), "A 股短线复盘助手", msgs)


def index():
    dist_index = os.path.join(_DIST, "index.html")
    if os.path.isfile(dist_index):
        return FileResponse(dist_index)
    return JSONResponse(
        {"error": "未找到前端构建产物，请先执行：cd frontend && npm install && npm run build"},
        status_code=503,
    )


@app.get("/api/verification/menu")
def api_verify_menu():
    """可选指标清单（前端下拉用）。"""
    from duanxian.verification import DIRECTIONS, METRICS

    return JSONResponse({
        "directions": DIRECTIONS,
        "metrics": [{"key": m.key, "label": m.label, "hint": m.hint,
                     "unit": m.unit, "higher_is_hotter": m.higher_is_hotter}
                    for m in METRICS],
    })


@app.get("/api/verification/items")
def api_verify_items(date: str):
    from duanxian import verification

    try:
        date = validate_trade_date(date)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"date": date, "items": verification.load_user_items(date)})


@app.post("/api/verification/items")
def api_verify_save(request: Request, date: str, body: dict = Body(...)):
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    from duanxian import verification

    try:
        date = validate_trade_date(date)
        result = verification.save_user_items(date, body.get("items") or [])
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    try:
        from duanxian import hooks, review_store

        rev = review_store.load(date)
        if rev is not None:
            hooks.RUNNER.emit_verification(date, rev)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 验证条件钩子派发失败（{date}）：{type(exc).__name__}: {exc}")

    return JSONResponse(result)


@app.get("/api/trade/phases")
def api_trade_phases():
    """六档清单与默认 Cap（前端下拉 / 说明）。"""
    rows = []
    for p in trade_budget.PHASES:
        ct, cs = trade_budget.caps_for(p)
        act = trade_budget.actions_for(p)
        rows.append({
            "phase": p, "cap_total": ct, "cap_single": cs,
            "allow": act["allow"], "forbid": act["forbid"],
        })
    return {"phases": rows}


@app.get("/api/trade/budget")
def api_trade_budget(date: str | None = None, refresh: int = 0):
    """某日仓位预算。默认读落盘；refresh=1 重算（保留手拨覆盖）。"""
    try:
        if not date:
            date = trade_calendar.latest_session() or china_today()
        date = validate_trade_date(date)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    try:
        if refresh:
            env = trade_store.refresh(date)
        else:
            env = trade_store.get_or_compute(date)
        return env
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.post("/api/trade/budget/refresh")
def api_trade_budget_refresh(request: Request, date: str | None = None):
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    try:
        if not date:
            date = trade_calendar.latest_session() or china_today()
        date = validate_trade_date(date)
        return trade_store.refresh(date)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.post("/api/trade/budget/override")
def api_trade_override(request: Request, date: str, body: dict = Body(...)):
    """人手覆盖当日档位；phase 为空则清除覆盖。"""
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    try:
        date = validate_trade_date(date)
        phase = body.get("phase")
        if phase == "" or phase is None:
            phase = None
        reason = str(body.get("reason") or "")
        return trade_store.set_override(date, phase, reason)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.get("/api/trade/account")
def api_trade_account():
    return trade_store.load_account()


@app.post("/api/trade/account/equity")
def api_trade_equity(request: Request, body: dict = Body(...)):
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    try:
        eq = float(body.get("equity"))
        note = str(body.get("note") or "")
        return trade_store.set_equity(eq, note)
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/trade/account/constants")
def api_trade_constants(request: Request, body: dict = Body(...)):
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    try:
        return trade_store.set_constants(**{
            k: body[k] for k in (
                "risk_per_trade", "daily_loss_limit", "max_dd_soft", "max_dd_hard",
            ) if k in body
        })
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/trade/account/snapshot")
def api_trade_snapshot(request: Request, date: str | None = None, body: dict | None = Body(None)):
    """写入当日权益快照（同日覆盖；可带命名账户栏位）。"""
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    try:
        if not date:
            date = trade_calendar.latest_session() or china_today()
        date = validate_trade_date(date)
        payload = body or {}
        mv = float(payload.get("market_value") or 0)
        fields = payload.get("account_fields")
        if not isinstance(fields, dict):
            # 允许扁平传栏位
            fields = {
                k: payload[k] for k in (
                    "account_name", "cash_balance", "account_display", "broker",
                    "available", "withdrawable", "frozen",
                    "stock_market_value", "position_pnl", "daily_pnl", "daily_pnl_pct",
                ) if k in payload
            } or None
        note = payload.get("note")
        return trade_store.snapshot_equity(
            date, mv, fields, note=None if note is None else str(note),
        )
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/api/watchlist")
def api_watchlist_get():
    """读取服务端自选股（插件写入或前端同步）。"""
    _add_vr_to_path()
    import watchlist as wl  # noqa: PLC0415

    return wl.get_watchlist()


@app.put("/api/watchlist")
def api_watchlist_put(request: Request, body: dict = Body(...)):
    """全量覆盖服务端自选股，并同步盯盘池。"""
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    _add_vr_to_path()
    import watchlist as wl  # noqa: PLC0415
    import watchtower as wt  # noqa: PLC0415

    try:
        out = wl.replace_codes(body.get("codes"))
        wt.set_watch(out["codes"])
        wt.poke()
        return out
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


def _portfolio_holdings() -> tuple[list, float]:
    """读 VR 持仓；失败当空。返回 (holdings, market_value)。"""
    try:
        import portfolio as pf

        data = pf.get_portfolio()
        hs = data.get("holdings") or []
        mv = float((data.get("totals") or {}).get("market_value") or 0)
        return hs, mv
    except Exception:  # noqa: BLE001
        return [], 0.0


@app.get("/api/trade/guard")
def api_trade_guard(date: str | None = None):
    """现仓 vs 上限、降档减仓顺序、当日亏损闸（有快照才启用）。"""
    try:
        if not date:
            date = trade_calendar.latest_session() or china_today()
        date = validate_trade_date(date)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    budget = trade_store.get_or_compute(date)
    account = trade_store.load_account()
    equity = account.get("equity")
    holdings, mv = _portfolio_holdings()
    consts = account.get("constants") or {}

    out: dict = {
        "date": date,
        "budget": budget,
        "equity": equity,
        "constants": consts,
        "position": None,
        "reduce_order": [],
        "daily_loss": None,
        "block_new_long_reasons": list(budget.get("block_new_long_reasons") or []),
    }
    if not budget.get("available"):
        return out
    if equity is None or float(equity) <= 0:
        out["block_new_long_reasons"] = out["block_new_long_reasons"] + ["未录入总权益"]
        return out

    eq = float(equity)
    cap_t = float(budget["cap_total"])
    cap_s = float(budget["cap_single"])
    pos = trade_budget.position_vs_caps(holdings, eq, cap_t, cap_s)
    out["position"] = pos
    out["reduce_order"] = trade_budget.reduce_order(holdings, eq, cap_t)
    if pos.get("over_total"):
        out["block_new_long_reasons"].append("总仓已达当前档 Cap_total")
    if not budget.get("expansion_allowed") and budget.get("phase") in (
        "过热防守", "退潮杀伤", "高潮拥挤",
    ):
        pass  # 理由已在 budget.block_new_long_reasons

    # 当日亏损：相对上一交易日权益快照
    prev = trade_calendar.prev_trade_date(date)
    snaps = account.get("snapshots") or {}
    prev_snap = snaps.get(prev) if prev else None
    if prev_snap and prev_snap.get("equity"):
        prev_eq = float(prev_snap["equity"])
        if prev_eq > 0:
            pnl_pct = (eq - prev_eq) / prev_eq
            limit = float(consts.get("daily_loss_limit") or trade_budget.DEFAULT_DAILY_LOSS_LIMIT)
            hit = pnl_pct <= -limit
            out["daily_loss"] = {
                "prev_date": prev,
                "prev_equity": prev_eq,
                "equity": eq,
                "pnl_pct": round(pnl_pct, 4),
                "limit": limit,
                "hit": hit,
            }
            if hit:
                out["block_new_long_reasons"].append(
                    f"触及当日亏损限额（{pnl_pct:.2%} ≤ -{limit:.0%}）"
                )
    return out


@app.post("/api/trade/screenshot/parse")
def api_trade_screenshot_parse(request: Request, body: dict = Body(...)):
    """上传券商持仓截图，用用户配置的识图模型解析为对照草稿（不落盘）。"""
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    image = body.get("image_b64") or body.get("image") or ""
    llm = body.get("llm") or {}
    if not isinstance(llm, dict):
        return JSONResponse({"error": "llm 配置无效"}, status_code=400)
    try:
        draft = screenshot_parse.parse_screenshot(str(image), llm)
        return {"ok": True, "draft": draft}
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.post("/api/trade/screenshot/apply")
def api_trade_screenshot_apply(request: Request, body: dict = Body(...)):
    """用户确认对照表后写入总权益、账户栏位、本地持仓，并按日覆盖写入快照。"""
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    try:
        equity, note, holdings, replace, fields = screenshot_parse.validate_apply_payload(body or {})
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    # 备注为空时用命名栏位格式化
    if not note.strip() and fields:
        note = trade_store.format_account_summary(fields)

    account = None
    if equity is not None:
        try:
            account = trade_store.set_equity(equity, note, fields=fields or None)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    elif fields or note:
        try:
            cur = trade_store.load_account()
            eq = cur.get("equity")
            if eq is not None:
                account = trade_store.set_equity(float(eq), note, fields=fields or None)
            elif fields:
                account = trade_store.set_account_fields(fields, note=note or None)
            else:
                account = trade_store.load_account()
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    portfolio = None
    try:
        import portfolio as pf
        import watchtower

        if replace:
            portfolio = pf.replace_holdings(holdings)
        else:
            for h in holdings:
                portfolio = pf.add_holding(h["code"], h["shares"], h["cost"])
            if portfolio is None:
                portfolio = pf.get_portfolio()
        watchtower.poke()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"写入持仓失败：{type(exc).__name__}: {exc}"}, status_code=500)

    # 按最近交易日覆盖写入日快照（含命名栏位）
    snap_date = None
    try:
        snap_date = trade_calendar.latest_session() or china_today()
        snap_date = validate_trade_date(snap_date)
        mv = float((portfolio or {}).get("totals", {}).get("market_value") or 0)
        if mv == 0 and fields.get("stock_market_value") is not None:
            mv = float(fields["stock_market_value"])
        account = trade_store.snapshot_equity(snap_date, mv, fields or None, note=note or None)
    except (TypeError, ValueError):
        account = account or trade_store.load_account()

    return {
        "ok": True,
        "account": account or trade_store.load_account(),
        "portfolio": portfolio,
        "written_holdings": len(holdings),
        "replace": replace,
        "snapshot_date": snap_date,
    }


@app.post("/api/trade/size")
def api_trade_size(request: Request, body: dict = Body(...)):
    """单笔金额计算器。"""
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    try:
        date = body.get("date") or trade_calendar.latest_session() or china_today()
        date = validate_trade_date(str(date))
        stop_pct = float(body["stop_pct"])
        boards = body.get("boards")
        if boards is not None:
            boards = int(boards)
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": f"参数错误：{exc}"}, status_code=400)

    budget = trade_store.get_or_compute(date)
    account = trade_store.load_account()
    equity = account.get("equity")
    if not budget.get("available"):
        return {"ok": False, "reason": budget.get("reason") or "预算不可用", "amount": 0}
    if equity is None or float(equity) <= 0:
        return {"ok": False, "reason": "请先录入总权益", "amount": 0}

    holdings, _ = _portfolio_holdings()
    used = sum(float(h.get("market_value") or 0) for h in holdings)
    risk = float((account.get("constants") or {}).get("risk_per_trade")
                 or trade_budget.DEFAULT_RISK_PER_TRADE)
    result = trade_budget.size_amount(
        float(equity),
        float(budget["cap_total"]),
        float(budget["cap_single"]),
        used,
        risk,
        stop_pct,
        boards=boards,
        phase=str(budget.get("phase") or "升温扩张"),
    )
    result["date"] = date
    result["phase"] = budget.get("phase")
    result["cap_total"] = budget.get("cap_total")
    result["cap_single"] = budget.get("cap_single")
    result["used"] = round(used, 2)
    return result


def _zt_fallback_date() -> str | None:
    try:
        import firstboard as _fb

        return (_fb.get_first_board() or {}).get("date")
    except Exception:  # noqa: BLE001
        return None


def _zt_import_guard(request: Request, body: dict):
    """写操作来源校验 + 取出粘贴文本。失败返回 JSONResponse，成功返回 str。"""
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源", "detail": "非法来源"}, status_code=403)
    text = str((body or {}).get("text") or "")
    if not text.strip():
        return JSONResponse({"error": "请粘贴同花顺导出的文本",
                             "detail": "请粘贴同花顺导出的文本"}, status_code=400)
    return text


@app.post("/api/market/first-board/parse-reasons")
def api_parse_zt_reasons(request: Request, body: dict = Body(...)):
    """解析同花顺涨停池 txt，只返回预览，不写入题材串缓存。"""
    text = _zt_import_guard(request, body)
    if not isinstance(text, str):
        return text
    from duanxian.zt_reason_import import ZtReasonImportError, parse_preview

    try:
        result = parse_preview(text, fallback_date=_zt_fallback_date())
    except ZtReasonImportError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)
    return {"data": {
        "ok": True,
        "date": result["date"],
        "count": result["count"],
        "skipped": result["skipped"],
        "rows": result["rows"],
    }}


@app.post("/api/market/first-board/import-reasons")
def api_import_zt_reasons(request: Request, body: dict = Body(...)):
    """导入同花顺涨停池 txt，解析涨停原因并写入题材串缓存。"""
    text = _zt_import_guard(request, body)
    if not isinstance(text, str):
        return text
    from duanxian.zt_reason_import import ZtReasonImportError, import_ths_text

    try:
        result = import_ths_text(text, fallback_date=_zt_fallback_date())
    except ZtReasonImportError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)

    try:
        import firstboard as _fb

        _fb.apply_imported_reasons(result["date_ymd"], result["reasons"])
    except Exception:  # noqa: BLE001
        pass

    return {"data": {
        "ok": True,
        "date": result["date"],
        "count": result["count"],
        "imported": result["imported"],
        "skipped": result["skipped"],
    }}


def _backup_guard(request: Request):
    """备份/导入是写盘操作，必须过本机来源闸。失败返回 JSONResponse。"""
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源", "detail": "非法来源"}, status_code=403)
    return None


@app.get("/api/config/theme-aliases")
def api_theme_aliases_get():
    """读取题材别名配置（涨停统计归一用）。"""
    from duanxian import theme_normalize as tn

    return {"data": tn.export_config()}


@app.post("/api/config/theme-aliases")
def api_theme_aliases_save(body: dict = Body(...)):
    """保存题材别名表。"""
    from duanxian.theme_normalize import ThemeAliasError, save_aliases

    raw = (body or {}).get("aliases")
    if not isinstance(raw, dict):
        return JSONResponse({"error": "aliases 须为对象", "detail": "aliases 须为对象"}, status_code=400)
    try:
        saved = save_aliases({str(k): str(v) for k, v in raw.items()})
    except ThemeAliasError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)
    return {"data": {"aliases": saved, "count": len(saved)}}


@app.post("/api/config/theme-aliases/reset")
def api_theme_aliases_reset():
    """恢复内置默认题材别名。"""
    from duanxian import theme_normalize as tn

    try:
        saved = tn.reset_aliases()
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)
    return {"data": {"aliases": saved, "count": len(saved)}}


@app.get("/api/config/zt-keywords")
def api_zt_keywords_get():
    """读取上涨关键词配置（首板深入分析闭集标签）。"""
    from duanxian import zt_keywords as zk

    return {"data": zk.export_config()}


@app.post("/api/config/zt-keywords")
def api_zt_keywords_save(body: dict = Body(...)):
    """保存上涨关键词列表。"""
    from duanxian.zt_keywords import ZtKeywordError, save_keywords

    raw = (body or {}).get("keywords")
    if not isinstance(raw, list):
        return JSONResponse({"error": "keywords 须为数组", "detail": "keywords 须为数组"}, status_code=400)
    try:
        saved = save_keywords([str(x) for x in raw])
    except ZtKeywordError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)
    return {"data": {"keywords": saved, "count": len(saved)}}


@app.post("/api/config/zt-keywords/reset")
def api_zt_keywords_reset():
    """恢复内置默认上涨关键词。"""
    from duanxian import zt_keywords as zk

    try:
        saved = zk.reset_keywords()
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)
    return {"data": {"keywords": saved, "count": len(saved)}}


@app.get("/api/experience/meta")
def api_experience_meta():
    """经验记忆库根路径与主题列表。"""
    from duanxian import experience as exp

    return {"data": exp.get_meta()}


@app.get("/api/experience/topic")
def api_experience_topic(name: str = ""):
    """读取单个主题 Markdown。"""
    from duanxian import experience as exp

    filename = (name or "").strip()
    if not filename:
        return JSONResponse({"error": "缺少 name", "detail": "缺少 name"}, status_code=400)
    try:
        return {"data": exp.read_topic(filename)}
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)


@app.post("/api/experience/retrieve")
def api_experience_retrieve(body: dict = Body(...)):
    """按问题关键词检索 Top-K 主题，供问答 / 全局问 AI 注入。"""
    from duanxian import experience as exp

    query = str((body or {}).get("query") or "").strip()
    try:
        k = int((body or {}).get("k") or 3)
    except (TypeError, ValueError):
        k = 3
    hits = exp.retrieve(query, k=k)
    return {"data": {
        "hits": hits,
        "context": exp.format_context(hits),
        "k": k,
    }}


@app.post("/api/experience/commit")
def api_experience_commit(request: Request, body: dict = Body(...)):
    """确认写入归纳后的主题文件，并刷新 index.md。"""
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源", "detail": "非法来源"}, status_code=403)
    from duanxian import experience as exp

    files = (body or {}).get("files")
    try:
        result = exp.commit_files(files if isinstance(files, list) else [])
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)
    return {"data": result}


def _plugin_row(rec) -> dict:
    from pathlib import Path

    p = Path(rec.path).expanduser()
    return {
        "id": rec.id,
        "path": rec.path,
        "name": rec.name,
        "version": rec.version,
        "enabled": rec.enabled,
        "registered_at": rec.registered_at,
        "file_exists": p.is_file(),
    }


@app.get("/api/plugins")
def api_plugins_list():
    """列出已注册钩子插件。"""
    from duanxian import plugin_store as ps

    rows = ps.list_plugins()
    return {
        "data": {
            "plugins": [_plugin_row(r) for r in rows],
            "registry_file": ps.registry_file(),
        }
    }


@app.post("/api/plugins/register")
def api_plugins_register(request: Request, body: Optional[dict] = Body(None)):
    """注册插件（.py 须导出 PACK）。"""
    blocked = _backup_guard(request)
    if blocked is not None:
        return blocked
    from duanxian import plugin_store as ps

    path = str((body or {}).get("path") or "").strip()
    if not path:
        return JSONResponse({"error": "请提供 path", "detail": "请提供 path"}, status_code=400)
    disabled = bool((body or {}).get("disabled"))
    try:
        rec = ps.register(path, enabled=not disabled)
    except (ValueError, TypeError, RuntimeError) as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    return {"data": _plugin_row(rec)}


@app.post("/api/plugins/enable")
def api_plugins_enable(request: Request, body: Optional[dict] = Body(None)):
    """启用插件。"""
    blocked = _backup_guard(request)
    if blocked is not None:
        return blocked
    from duanxian import plugin_store as ps

    plugin = str((body or {}).get("plugin") or "").strip()
    if not plugin:
        return JSONResponse({"error": "请提供 plugin", "detail": "请提供 plugin"}, status_code=400)
    try:
        rec = ps.set_enabled(plugin, True)
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    return {"data": _plugin_row(rec)}


@app.post("/api/plugins/disable")
def api_plugins_disable(request: Request, body: Optional[dict] = Body(None)):
    """停用插件。"""
    blocked = _backup_guard(request)
    if blocked is not None:
        return blocked
    from duanxian import plugin_store as ps

    plugin = str((body or {}).get("plugin") or "").strip()
    if not plugin:
        return JSONResponse({"error": "请提供 plugin", "detail": "请提供 plugin"}, status_code=400)
    try:
        rec = ps.set_enabled(plugin, False)
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    return {"data": _plugin_row(rec)}


@app.post("/api/plugins/uninstall")
def api_plugins_uninstall(request: Request, body: Optional[dict] = Body(None)):
    """从注册表卸载插件（不删除 .py 文件）。"""
    blocked = _backup_guard(request)
    if blocked is not None:
        return blocked
    from duanxian import plugin_store as ps

    plugin = str((body or {}).get("plugin") or "").strip()
    if not plugin:
        return JSONResponse({"error": "请提供 plugin", "detail": "请提供 plugin"}, status_code=400)
    try:
        rec = ps.uninstall(plugin)
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    return {"data": _plugin_row(rec)}


@app.post("/api/plugins/pick")
def api_plugins_pick(request: Request, body: Optional[dict] = Body(None)):
    """弹出系统文件选择框，选取 .py 插件入口。"""
    blocked = _backup_guard(request)
    if blocked is not None:
        return blocked
    from duanxian import plugin_store as ps

    initial = str((body or {}).get("initial_dir") or "").strip()
    try:
        picked = ps.pick_entry_file(initial or None)
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)
    if not picked:
        return {"data": {"cancelled": True}}
    return {"data": {"cancelled": False, "path": picked}}


@app.post("/api/plugins/open-dir")
def api_plugins_open_dir(request: Request, body: Optional[dict] = Body(None)):
    """用系统文件管理器打开插件入口所在目录。"""
    blocked = _backup_guard(request)
    if blocked is not None:
        return blocked
    from duanxian import plugin_store as ps

    raw_path = str((body or {}).get("path") or "").strip()
    plugin = str((body or {}).get("plugin") or "").strip()
    if plugin and not raw_path:
        try:
            pid = ps.resolve_id(plugin)
        except ValueError as exc:
            return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
        hit = next((r for r in ps.list_plugins() if r.id == pid), None)
        if hit is None:
            return JSONResponse({"error": f"未找到插件：{pid}", "detail": f"未找到插件：{pid}"}, status_code=400)
        raw_path = hit.path
    if not raw_path:
        return JSONResponse({"error": "请提供 path 或 plugin", "detail": "请提供 path 或 plugin"}, status_code=400)
    try:
        opened = ps.open_entry_dir(raw_path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)
    return {"data": {"ok": True, "path": opened}}


@app.get("/api/backup/status")
def api_backup_status():
    """当前可备份数据规模（~/.duanxian-agents 非日志文件）。"""
    from duanxian import backup

    return {"data": backup.overview()}


@app.post("/api/backup/open")
def api_backup_open(request: Request, body: Optional[dict] = Body(None)):
    """用系统文件管理器打开数据根目录或 cache 目录。"""
    blocked = _backup_guard(request)
    if blocked is not None:
        return blocked
    from duanxian import backup
    from duanxian.backup import BackupError

    kind = str((body or {}).get("kind") or "root")
    try:
        return {"data": backup.open_data_dir(kind)}
    except BackupError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)


@app.post("/api/backup/export")
def api_backup_export(request: Request, body: Optional[dict] = Body(None)):
    """把非日志数据打包成 zip，写到本机指定目录。"""
    blocked = _backup_guard(request)
    if blocked is not None:
        return blocked
    from duanxian import backup
    from duanxian.backup import BackupError

    dest = str((body or {}).get("dest_dir") or "")
    try:
        return {"data": backup.export_to_dir(dest)}
    except BackupError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)


@app.get("/api/backup/download")
def api_backup_download(request: Request):
    """把非日志数据打包成 zip，由浏览器下载。"""
    blocked = _backup_guard(request)
    if blocked is not None:
        return blocked
    import shutil
    import tempfile as _tempfile

    from starlette.background import BackgroundTask

    from duanxian import backup
    from duanxian.backup import BackupError

    tmp_dir = _tempfile.mkdtemp(prefix="vibe-backup-")
    try:
        result = backup.export_to_dir(tmp_dir)
        path = result["path"]
    except BackupError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    except OSError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)

    def _cleanup() -> None:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return FileResponse(
        path,
        filename=result["filename"],
        media_type="application/zip",
        background=BackgroundTask(_cleanup),
    )


@app.post("/api/backup/import")
def api_backup_import(request: Request, body: Optional[dict] = Body(None)):
    """从本机 zip / 文件夹路径，或上传的 zip（base64）导入数据。"""
    blocked = _backup_guard(request)
    if blocked is not None:
        return blocked
    from duanxian import backup
    from duanxian.backup import BackupError

    blob = str((body or {}).get("content_b64") or "")
    src = str((body or {}).get("path") or "")
    try:
        if blob.strip():
            result = backup.import_from_base64(blob)
        elif src.strip():
            result = backup.import_from_path(src)
        else:
            raise BackupError("请选择压缩包，或填写本机 zip / 文件夹路径")
        return {"data": result}
    except BackupError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=400)
    except OSError as exc:
        return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=500)


def _mount_static() -> None:
    """挂静态资源 + SPA 兜底"""
    if not os.path.isdir(_DIST):
        print(f"ℹ️ 未找到前端构建产物（{_DIST}）。请先执行："
              f"cd frontend && npm install && npm run build")
        return
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")),
              name="assets")

    @app.get("/{full_path:path}")
    def _spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"error": f"未知接口 /{full_path}"}, status_code=404)
        # 真实存在的静态文件（favicon / manifest / 图片…）直接给
        candidate = safe_join(_DIST, full_path) if full_path else None
        if candidate and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_DIST, "index.html"))

    print(f"✓ React 构建产物已挂载（{_DIST}）")


_mount_static()

if __name__ == "__main__":
    import uvicorn

    # 端口可用 VIBE_PORT 覆盖，默认 8910（被占时不必改代码）
    port = int(os.environ.get("VIBE_PORT", "8910"))
    if _DISABLED_CLIS:
        # 有声地说出限制：不说的话，"少了几个可选项"看起来像 bug 而不是有意为之
        print(f"🔒 已禁用自动批准 CLI：{', '.join(_DISABLED_CLIS)}"
              f"（保留 {', '.join(sorted(_ALLOWED_CLI_KINDS))}）")
    if _opted_in_clis():
        # 放开了危险 CLI 就必须说清放开了什么、代价是什么 ——
        # 光印一句"保留 claude, codex"看不出后者是被特批进来的
        print(f"⚠️  VIBE_ALLOW_UNSAFE_CLI 已放开：{', '.join(sorted(_opted_in_clis()))}"
              f" —— 这些 CLI 会不经询问地读写文件、执行命令，"
              f"而问 AI 时抓来的外部新闻原文会原样进 prompt。确认你信任数据源再用。")
    # VIBE_RELOAD=1：源码变化后自动重启。必须传 import 字符串，传 app 对象时
    # uvicorn 会静默关掉 reload。只盯仓库里的 .py，避开 frontend / tests。
    reload = os.environ.get("VIBE_RELOAD", "").strip().lower() in ("1", "true", "yes")
    if reload:
        print("↻ 开发模式：Python 源码变化后自动重启")
        print(f"→ 后端 http://127.0.0.1:{port}  （VR 分栏路由 {_VR_ROUTES} 条已并入）")
        print("→ 改前端请打开 Vite Watch（默认 http://127.0.0.1:5910 ）")
        uvicorn.run(
            "server:app",
            host="127.0.0.1",
            port=port,
            reload=True,
            reload_dirs=[_HERE],
            reload_includes=["*.py"],
            reload_excludes=["frontend/*", "tests/*", "scripts/*"],
        )
    else:
        print(f"→ 打开 http://127.0.0.1:{port}  （VR 分栏路由 {_VR_ROUTES} 条已并入）")
        uvicorn.run(app, host="127.0.0.1", port=port)
