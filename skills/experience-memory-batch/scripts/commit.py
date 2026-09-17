#!/usr/bin/env python3
"""把整理后的经验 JSON 写入经验记忆库并刷新 index.md。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ensure_path() -> None:
    root = _repo_root()
    for item in (root, root / "vr"):
        text = str(item)
        if text not in sys.path:
            sys.path.insert(0, text)


def load_payload(raw: str) -> list[dict]:
    data = json.loads(raw)
    if isinstance(data, list):
        files = data
    elif isinstance(data, dict):
        files = data.get("files")
    else:
        files = None
    if not isinstance(files, list) or not files:
        raise SystemExit("JSON 须为 {\"files\": [...]} 或非空数组")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="写入经验记忆主题")
    parser.add_argument(
        "source",
        help="JSON 文件路径，或 - 表示 stdin",
    )
    args = parser.parse_args()
    if args.source == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.source).read_text(encoding="utf-8")

    _ensure_path()
    from duanxian import experience as exp

    files = load_payload(raw)
    result = exp.commit_files(files)
    written = result.get("written") or []
    summary = {
        "ok": result.get("ok"),
        "root": result.get("root"),
        "written_count": len(written),
        "written": [
            {
                "filename": w.get("filename"),
                "title": w.get("title"),
                "date": w.get("date"),
                "category": w.get("category"),
                "summary": w.get("summary"),
            }
            for w in written
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    code = main()
    # 个股/板块解析可能留下非 daemon 线程，普通 return 会挂起
    os._exit(code)
