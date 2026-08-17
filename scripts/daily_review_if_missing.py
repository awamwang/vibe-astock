"""交易日晚间幂等复盘：当日无可用复盘则跑 main.py，并校验落盘文件。

用法：
    .venv/Scripts/python scripts/daily_review_if_missing.py
    .venv/Scripts/python scripts/daily_review_if_missing.py --repo G:/Projects/Stock/vibe-astock

退出码：
    0  已有复盘 / 非交易日跳过 / 本次生成并校验通过
    1  参数或运行错误
    2  LLM 配置错误
    3  体检拒绝（核心数据缺失）
    4  跑完后落盘文件不可用
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="交易日晚间：缺复盘则生成并校验")
    p.add_argument(
        "--repo",
        default=os.environ.get("VIBE_ASTOCK_REPO")
        or str(Path(__file__).resolve().parents[1]),
        help="项目根目录（含 main.py / .venv）",
    )
    p.add_argument(
        "--python",
        default=None,
        help="Python 解释器；默认用仓库 .venv/Scripts/python.exe",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="即使已有可用复盘也重新跑（仍要求今日是已收盘交易日）",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    repo = Path(args.repo).resolve()
    if not (repo / "main.py").is_file():
        _log(f"✗ 不是有效项目目录（缺 main.py）：{repo}")
        return 1

    py = Path(args.python) if args.python else repo / ".venv" / "Scripts" / "python.exe"
    if not py.is_file():
        # 非 Windows / 未建 venv 时回退当前解释器
        py = Path(sys.executable)
    _log(f"仓库={repo}")
    _log(f"Python={py}")

    os.chdir(repo)
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    from duanxian import review_store, trade_calendar
    from duanxian.util import china_today

    today = china_today()
    session = trade_calendar.latest_session()
    _log(f"今日={today}  最近已收盘交易日={session}")

    if session != today:
        _log("跳过：今日不是已收盘交易日（周末/节假日或盘面未定稿）")
        return 0

    existing = review_store.load(today)
    if existing is not None and review_store.usable(existing) and not args.force:
        path = Path(review_store.DIR) / f"{today}.json"
        _log(f"跳过：已有可用复盘 → {path}")
        return 0

    _log(f"开始复盘 {today} …")
    t0 = time.time()
    proc = subprocess.run(
        [str(py), "main.py", today],
        cwd=str(repo),
        check=False,
    )
    _log(f"main.py 退出码={proc.returncode}  耗时={time.time() - t0:.0f}s")
    if proc.returncode == 2:
        return 2
    if proc.returncode == 3:
        return 3
    if proc.returncode != 0:
        return 1

    saved = review_store.load(today)
    path = Path(review_store.DIR) / f"{today}.json"
    if not path.is_file():
        _log(f"✗ 校验失败：文件不存在 {path}")
        return 4
    if saved is None or not review_store.usable(saved):
        _log(f"✗ 校验失败：{path} 存在但内容不可用（focus/focus_md 为空）")
        return 4

    _log(f"✓ 复盘已生成且可用 → {path}（{path.stat().st_size} bytes）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
