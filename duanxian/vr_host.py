"""VR host —— 合并 VR 路由、钉定稿涨停池、CLI 白名单、用户数据防护。

`vr/` 保持可整树拷贝同步（ADR-0001）；本模块在外围拥有 host 策略，
HTTP 领域路由仍留在 `server.py` 薄适配层。
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Optional

from fastapi import FastAPI

from . import trade_calendar
from .cli_llm import _BINS_ATTR_NAME as _BINS_ATTR
from .util import china_now

# 由 `bind` 注入：目标 FastAPI 与仓库根目录
_app: Optional[FastAPI] = None
_here: str = ""

_VR_PATH_RES: list[re.Pattern] = []


def bind(app: FastAPI, here: str) -> None:
    """绑定宿主 app 与仓库根路径，供后续 merge / path 使用。"""
    global _app, _here
    _app = app
    _here = here


def _alert(msg: str) -> None:
    """必达的告警输出"""
    print(msg, file=sys.stderr, flush=True)


def _merge_vr_routes() -> int:
    """把 `vr/` 的路由并进本 app。返回并入条数；失败不影响本仓库自有功能。"""
    if _app is None or not _here:
        _alert("⚠️ VR 后端并入失败：未 bind 宿主 app")
        return 0
    vr_dir = os.path.join(_here, "vr")
    if not os.path.isdir(vr_dir):
        return 0
    if vr_dir not in sys.path:
        sys.path.insert(0, vr_dir)   # 放最前，确保 `import astock` 等解析到 vr/ 内
    try:
        import app as vr_app  # noqa: PLC0415  vr/app.py（不是本仓库的模块）

        # server reload 时本模块不重载；先清空再收集，避免路径正则叠两份
        _VR_PATH_RES.clear()
        before = len(_app.router.routes)
        # 只拿 /api/* 的；VR 没有非 /api 路由，这层过滤是为了防它日后加了根路由
        # 把我们的 SPA fallback 顶掉
        for r in vr_app.app.router.routes:
            path = getattr(r, "path", "")
            if not path.startswith("/api/"):
                continue
            _app.router.routes.append(r)
            # 记下路径模板 → 正则（`{rid}` 这类参数换成"一段非斜杠"），
            # 供下面那道补偿闸判断"这个请求是不是打在 VR 路由上"
            _VR_PATH_RES.append(re.compile(
                "^" + re.sub(r"\{[^}]+\}", r"[^/]+", re.escape(path)
                             .replace(r"\{", "{").replace(r"\}", "}")) + "$"))
        return len(_app.router.routes) - before
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


def refresh_allowed_cli_kinds() -> frozenset[str]:
    """按当前环境变量重算 CLI 白名单（server reload 时调用）。"""
    global _ALLOWED_CLI_KINDS
    _ALLOWED_CLI_KINDS = _SAFE_CLI_KINDS | _opted_in_clis()
    return _ALLOWED_CLI_KINDS


_ALLOWED_CLI_KINDS = _SAFE_CLI_KINDS | _opted_in_clis()

# 已知并有意禁掉的。只用于区分「预期内」和「上游新来的」，**不参与放行判断**
# —— 放行只看白名单，这个集合少写了什么也不会让谁被放进来。
_KNOWN_UNSAFE_CLIS = frozenset({"qwen", "deepseek", "codex", "opencode", "cursor", "kimi"})

# 摘除前的完整 CLI 定义快照 —— 给 `/api/cli/available` 报"这个 kind 装没装"用。
# 摘掉之后 `detect_cli()` 一律返回 None，分不清"没装"和"被禁"，而这两件事
# 对用户是完全不同的信息（一个去装、一个别想了）。
_ALL_CLI_BINS: dict[str, list[str]] = {}


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
    vr_dir = os.path.join(_here, "vr") if _here else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vr")
    if os.path.isdir(vr_dir) and vr_dir not in sys.path:
        sys.path.insert(0, vr_dir)


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


def _is_vr_path(path: str) -> bool:
    return any(rx.match(path) for rx in _VR_PATH_RES)


def install(app: FastAPI, here: str) -> dict[str, Any]:
    """挂上 VR host：并路由、钉定稿池、备份 userdata、灌自选、摘不安全 CLI。"""
    bind(app, here)
    refresh_allowed_cli_kinds()
    routes = _merge_vr_routes()
    pinned = _pin_pool_to_settled_session()
    _guard_vr_userdata()
    _bootstrap_watchlist()
    disabled = _disable_unsafe_clis()
    return {
        "routes": routes,
        "pinned": pinned,
        "disabled_clis": disabled,
    }
