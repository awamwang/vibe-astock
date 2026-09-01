"""本机写盘根目录（profile）。

默认 profile = 当前用户主目录，落盘布局与原先一致：
  {profile}/.duanxian-agents/
  {profile}/.vibe-research/
  {profile}/.vibe-astock/
  {profile}/.config/mimo/mimo.env

指定 profile（CLI `--profile` / 环境变量 `VIBE_PROFILE`）后：
- 上述目录都相对该路径建立；
- 若配置文件尚不存在，则按内置默认初始化生成。

派生环境变量（有显式值时不覆盖）：
  DUANXIAN_AGENTS_DIR / VR_DATA_DIR / VIBE_ASTOCK_DIR
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable

from .util import atomic_write_json

ENV_PROFILE = "VIBE_PROFILE"
ENV_AGENTS = "DUANXIAN_AGENTS_DIR"
ENV_ASTOCK = "VIBE_ASTOCK_DIR"
ENV_VR = "VR_DATA_DIR"

_explicit: Path | None = None
_rebinders: list[Callable[[], None]] = []


def profile_root() -> Path:
    """当前 profile 根目录（显式 set > 环境变量 > 用户主目录）。"""
    if _explicit is not None:
        return _explicit
    raw = (os.environ.get(ENV_PROFILE) or "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return Path.home()


def is_custom_profile() -> bool:
    """是否使用了非默认主目录的 profile（CLI 或环境变量）。"""
    if _explicit is not None:
        return True
    return bool((os.environ.get(ENV_PROFILE) or "").strip())


def agents_dir() -> Path:
    raw = (os.environ.get(ENV_AGENTS) or "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return profile_root() / ".duanxian-agents"


def research_dir() -> Path:
    raw = (os.environ.get(ENV_VR) or "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return profile_root() / ".vibe-research"


def astock_dir() -> Path:
    raw = (os.environ.get(ENV_ASTOCK) or "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return profile_root() / ".vibe-astock"


def mimo_env_path() -> Path:
    return profile_root() / ".config" / "mimo" / "mimo.env"


def config_dir() -> Path:
    return agents_dir() / "config"


def register_rebind(fn: Callable[[], None]) -> Callable[[], None]:
    """注册路径重绑回调：模块 import 时执行一次，set_profile 时再执行。"""
    _rebinders.append(fn)
    fn()
    return fn


def _sync_derived_env(root: Path) -> None:
    """把 profile 派生目录写入环境变量，供 vr/ 等不依赖本模块的代码读取。"""
    os.environ[ENV_PROFILE] = str(root)
    os.environ[ENV_AGENTS] = str(root / ".duanxian-agents")
    os.environ[ENV_ASTOCK] = str(root / ".vibe-astock")
    if not (os.environ.get(ENV_VR) or "").strip():
        os.environ[ENV_VR] = str(root / ".vibe-research")


def _run_rebinders() -> None:
    for fn in list(_rebinders):
        fn()


def set_profile(
    path: str | Path,
    *,
    init_config: bool = True,
) -> Path:
    """指定 profile 根目录；可选初始化缺失的配置文件。"""
    global _explicit
    root = Path(os.path.expanduser(str(path))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    _explicit = root
    _sync_derived_env(root)
    _run_rebinders()
    if init_config:
        ensure_profile_initialized()
    return root


def clear_profile_override() -> None:
    """测试用：清除显式 profile，回到环境变量 / 主目录。"""
    global _explicit
    _explicit = None
    _run_rebinders()


def consume_profile_arg(argv: list[str] | None = None) -> tuple[list[str], Path | None]:
    """从 argv 抽出 `--profile`，返回 (剩余参数, profile 或 None)。

    不用短选项 `-p`，避免与 pytest `-p` 等工具冲突。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--profile", default=None)
    ns, rest = parser.parse_known_args(args)
    raw = (ns.profile or "").strip()
    if not raw:
        return rest, None
    return rest, Path(os.path.expanduser(raw)).resolve()


def bootstrap(*, profile: str | Path | None = None, init_config: bool | None = None) -> Path:
    """进程入口：应用 CLI/显式 profile，或同步环境变量中的自定义 profile。"""
    if profile is not None:
        do_init = True if init_config is None else init_config
        return set_profile(profile, init_config=do_init)
    root = profile_root()
    if is_custom_profile():
        _sync_derived_env(root)
        _run_rebinders()
        if init_config is not False:
            ensure_profile_initialized()
    return root


def _write_json_if_missing(path: Path, payload: dict) -> bool:
    if path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    return bool(atomic_write_json(str(path), payload))


def ensure_profile_initialized() -> dict[str, list[str]]:
    """若配置/骨架目录缺失则生成；已存在的文件不覆盖。"""
    created: list[str] = []
    dirs: list[str] = []

    agents = agents_dir()
    research = research_dir()
    astock = astock_dir()
    cfg = config_dir()

    for d in (
        agents,
        agents / "config",
        agents / "reviews",
        agents / "weekly",
        agents / "cache",
        agents / "trade",
        agents / "messages",
        agents / "reflections",
        agents / "verification",
        agents / "experience",
        agents / "articles",
        agents / "leaders",
        research,
        astock,
        mimo_env_path().parent,
    ):
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            dirs.append(str(d))

    # —— 配置默认（与各模块 reset/默认 schema 对齐）——
    seeds: list[tuple[Path, dict]] = [
        (cfg / "trade_phases.json", {"schema": 1, "phases": []}),
        (cfg / "trade_thresholds.json", {"schema": 1, "thresholds": {}}),
        (
            cfg / "sentiment_s.json",
            {"schema": 1, "method": "hard_rules", "fusionintel_api_key": ""},
        ),
        (cfg / "message_follow_keywords.json", {"schema": 1, "keywords": []}),
        (cfg / "message_follow_blocks.json", {"schema": 1, "blocks": []}),
        (cfg / "message_default_end_days.json", {"schema": 1, "default_end_days": 5}),
        (astock / "plugins.json", {"schema": 1, "plugins": []}),
    ]

    # zt_keywords / theme_aliases 带业务默认，延迟 import 避免环依赖
    try:
        from . import zt_keywords as zk

        seeds.append(
            (cfg / "zt_keywords.json", {"schema": 1, "keywords": zk.default_keywords()})
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import theme_normalize as tn

        aliases = tn.default_aliases()
        seeds.append(
            (
                cfg / "theme_aliases.json",
                {
                    "schema": 2,
                    "aliases": aliases,
                    "types": {a: "" for a in aliases},
                },
            )
        )
    except Exception:  # noqa: BLE001
        pass

    for path, payload in seeds:
        if _write_json_if_missing(path, payload):
            created.append(str(path))

    return {"dirs": dirs, "files": created}


def describe() -> dict[str, str]:
    """供调试 / API 查看当前落盘根。"""
    return {
        "profile": str(profile_root()),
        "agents": str(agents_dir()),
        "research": str(research_dir()),
        "astock": str(astock_dir()),
        "mimo_env": str(mimo_env_path()),
        "custom": str(is_custom_profile()).lower(),
    }
