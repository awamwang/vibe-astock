#!/usr/bin/env python3
"""项目版本发布工具：推进版本、同步代码中的版本号、写变更日志、打 git tag。

用法（在仓库根目录）::

    python scripts/release.py status
    python scripts/release.py sync [--dry-run]
    python scripts/release.py bump patch|minor|major|x.y.z [选项]
    python scripts/release.py preview   # 预览自上次 tag 以来的提交归类

选项::

    --dry-run       只打印将要做的事，不改文件、不提交、不打 tag
    --no-commit     改文件与 CHANGELOG，但不 git commit
    --no-tag        提交后不打 annotated tag
    --allow-dirty   允许在工作区有未提交改动时 bump（默认拒绝）
    -m / --message  写入 CHANGELOG 顶部的发布摘要（一行或多行）

示例::

    python scripts/release.py bump patch -m "消息关注板块与仓位预算文档"
    python scripts/release.py bump 0.2.0 --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"
TAG_PREFIX = "v"

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")


# ---------------------------------------------------------------------------
# 版本目标：所有需要随发布一起改动的文件
# ---------------------------------------------------------------------------


class VersionHit(NamedTuple):
    path: Path
    found: str | None
    expected_forms: tuple[str, ...]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def parse_semver(raw: str) -> tuple[int, int, int]:
    text = raw.strip().lstrip("vV")
    m = SEMVER_RE.match(text)
    if not m:
        raise ValueError(f"无效语义化版本: {raw!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def format_semver(parts: tuple[int, int, int]) -> str:
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def bump_semver(current: str, part: str) -> str:
    major, minor, patch = parse_semver(current)
    if part == "major":
        return format_semver((major + 1, 0, 0))
    if part == "minor":
        return format_semver((major, minor + 1, 0))
    if part == "patch":
        return format_semver((major, minor, patch + 1))
    # 显式版本号
    return format_semver(parse_semver(part))


def read_version() -> str:
    if VERSION_FILE.is_file():
        text = VERSION_FILE.read_text(encoding="utf-8").strip()
        if text:
            return format_semver(parse_semver(text))
    # 回退：从 package.json 读
    pkg = ROOT / "frontend" / "package.json"
    data = json.loads(_read_text(pkg))
    return format_semver(parse_semver(str(data["version"])))


def write_version_file(version: str) -> None:
    _write_text(VERSION_FILE, version + "\n")


# ---------------------------------------------------------------------------
# 各文件同步逻辑
# ---------------------------------------------------------------------------


def _sub_once(text: str, pattern: str, repl: str, path: Path, label: str) -> str:
    new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
    if n != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: 未能唯一定位 {label}（命中 {n} 处）")
    return new


def sync_package_json(version: str) -> None:
    path = ROOT / "frontend" / "package.json"
    data = json.loads(_read_text(path))
    data["version"] = version
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def sync_package_lock(version: str) -> None:
    path = ROOT / "frontend" / "package-lock.json"
    data = json.loads(_read_text(path))
    data["version"] = version
    packages = data.get("packages")
    if isinstance(packages, dict) and "" in packages and isinstance(packages[""], dict):
        packages[""]["version"] = version
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def sync_hook_schemas(version: str) -> None:
    path = ROOT / "duanxian" / "hook_schemas.py"
    text = _read_text(path)
    text = _sub_once(
        text,
        r'(ENGINE_VERSION\s*=\s*")[^"]*(")',
        rf"\g<1>{version}\2",
        path,
        "ENGINE_VERSION",
    )
    _write_text(path, text)


def sync_vr_app(version: str) -> None:
    path = ROOT / "vr" / "app.py"
    text = _read_text(path)
    text = _sub_once(
        text,
        r'(FastAPI\(title="Vibe-Research API",\s*version=")[^"]*(")',
        rf"\g<1>{version}\2",
        path,
        "FastAPI version",
    )
    text = _sub_once(
        text,
        r'(return\s*\{\s*"ok":\s*True,\s*"service":\s*"vibe-research-api",\s*"version":\s*")[^"]*(")',
        rf"\g<1>{version}\2",
        path,
        "health version",
    )
    _write_text(path, text)


def sync_frontend_const(path: Path, version: str) -> None:
    text = _read_text(path)
    text = _sub_once(
        text,
        r'(APP_VERSION\s*=\s*")v?[^"]*(")',
        rf"\g<1>v{version}\2",
        path,
        "APP_VERSION",
    )
    _write_text(path, text)


def sync_readme_badge(path: Path, version: str) -> None:
    text = _read_text(path)
    text = _sub_once(
        text,
        r"(badge/version-v)[0-9]+\.[0-9]+\.[0-9]+(-orange)",
        rf"\g<1>{version}\2",
        path,
        "version badge",
    )
    _write_text(path, text)


def sync_doc_engine_version(path: Path, version: str) -> None:
    """文档中的 ENGINE_VERSION「当前 `x.y.z`」与示例 engine_version。"""
    if not path.is_file():
        return
    original = _read_text(path)
    if "ENGINE_VERSION" not in original and "engine_version" not in original:
        return
    text = re.sub(
        r"(ENGINE_VERSION[^`\n]*当前\s*`)\d+\.\d+\.\d+(`)",
        rf"\g<1>{version}\2",
        original,
    )
    text = re.sub(
        r'("engine_version"\s*:\s*")\d+\.\d+\.\d+(")',
        rf"\g<1>{version}\2",
        text,
    )
    if text != original:
        _write_text(path, text)


def apply_version(version: str) -> list[str]:
    """把 version 写入所有已知目标，返回已更新的相对路径列表。"""
    touched: list[str] = []

    write_version_file(version)
    touched.append("VERSION")

    sync_package_json(version)
    touched.append("frontend/package.json")

    sync_package_lock(version)
    touched.append("frontend/package-lock.json")

    sync_hook_schemas(version)
    touched.append("duanxian/hook_schemas.py")

    sync_vr_app(version)
    touched.append("vr/app.py")

    for rel in (
        "frontend/src/components/layout/Layout.tsx",
        "frontend/src/pages/About.tsx",
    ):
        p = ROOT / rel
        if p.is_file():
            sync_frontend_const(p, version)
            touched.append(rel)

    for rel in ("README.md", "README_en.md"):
        p = ROOT / rel
        if p.is_file():
            sync_readme_badge(p, version)
            touched.append(rel)

    for rel in (
        "doc/development/hook-lifecycle.md",
        "docs/development/hook-lifecycle.md",
        "doc/development/plugin-development.md",
        "docs/development/plugin-development.md",
    ):
        p = ROOT / rel
        before = _read_text(p) if p.is_file() else None
        sync_doc_engine_version(p, version)
        if before is not None and p.is_file() and _read_text(p) != before:
            touched.append(rel)

    return touched


# ---------------------------------------------------------------------------
# 探测各文件当前版本（status）
# ---------------------------------------------------------------------------


def _find_first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.M)
    return m.group(1) if m else None


def collect_version_hits(expected: str) -> list[VersionHit]:
    hits: list[VersionHit] = []
    v = expected
    tagged = f"v{v}"

    hits.append(
        VersionHit(
            VERSION_FILE,
            VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else None,
            (v,),
        )
    )

    pkg = ROOT / "frontend" / "package.json"
    data = json.loads(_read_text(pkg))
    hits.append(VersionHit(pkg, str(data.get("version")), (v,)))

    lock = ROOT / "frontend" / "package-lock.json"
    lock_data = json.loads(_read_text(lock))
    lock_root = lock_data.get("version")
    lock_pkg = None
    packages = lock_data.get("packages")
    if isinstance(packages, dict) and isinstance(packages.get(""), dict):
        lock_pkg = packages[""].get("version")
    hits.append(VersionHit(lock, f"{lock_root}/{lock_pkg}", (f"{v}/{v}",)))

    hs = ROOT / "duanxian" / "hook_schemas.py"
    hits.append(
        VersionHit(
            hs,
            _find_first(r'ENGINE_VERSION\s*=\s*"([^"]*)"', _read_text(hs)),
            (v,),
        )
    )

    app = ROOT / "vr" / "app.py"
    app_text = _read_text(app)
    fastapi_v = _find_first(r'FastAPI\(title="Vibe-Research API",\s*version="([^"]*)"', app_text)
    health_v = _find_first(
        r'return\s*\{\s*"ok":\s*True,\s*"service":\s*"vibe-research-api",\s*"version":\s*"([^"]*)"',
        app_text,
    )
    hits.append(VersionHit(app, f"{fastapi_v}/{health_v}", (f"{v}/{v}",)))

    for rel in (
        "frontend/src/components/layout/Layout.tsx",
        "frontend/src/pages/About.tsx",
    ):
        p = ROOT / rel
        if not p.is_file():
            hits.append(VersionHit(p, None, (tagged,)))
            continue
        found = _find_first(r'APP_VERSION\s*=\s*"([^"]*)"', _read_text(p))
        hits.append(VersionHit(p, found, (tagged,)))

    for rel in ("README.md", "README_en.md"):
        p = ROOT / rel
        if not p.is_file():
            continue
        found = _find_first(r"badge/version-v([0-9]+\.[0-9]+\.[0-9]+)", _read_text(p))
        hits.append(VersionHit(p, found, (v,)))

    return hits


# ---------------------------------------------------------------------------
# Git / CHANGELOG
# ---------------------------------------------------------------------------


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def git_ok() -> bool:
    r = run_git("rev-parse", "--is-inside-work-tree", check=False)
    return r.returncode == 0 and r.stdout.strip() == "true"


def git_dirty() -> bool:
    r = run_git("status", "--porcelain")
    return bool(r.stdout.strip())


def latest_tag() -> str | None:
    r = run_git("describe", "--tags", "--abbrev=0", check=False)
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def tag_exists(tag: str) -> bool:
    r = run_git("rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False)
    return r.returncode == 0


def commits_since(ref: str | None) -> list[str]:
    rng = f"{ref}..HEAD" if ref else "HEAD"
    r = run_git("log", rng, "--pretty=format:%s", check=False)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


_TYPE_MAP = (
    ("feat", "新增"),
    ("fix", "修复"),
    ("docs", "文档"),
    ("refactor", "重构"),
    ("perf", "性能"),
    ("test", "测试"),
    ("chore", "杂项"),
    ("ci", "杂项"),
    ("build", "杂项"),
    ("style", "杂项"),
)

_CONVENTIONAL = re.compile(
    r"^(?P<type>feat|fix|docs|refactor|perf|test|chore|ci|build|style)"
    r"(?:\([^)]*\))?!?:\s*(?P<sub>.+)$",
    re.I,
)


def classify_commits(subjects: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    type_to_zh = {k: v for k, v in _TYPE_MAP}
    for subj in subjects:
        m = _CONVENTIONAL.match(subj)
        if m:
            zh = type_to_zh.get(m.group("type").lower(), "其他")
            item = m.group("sub").strip()
        else:
            zh = "其他"
            item = subj
        groups.setdefault(zh, []).append(item)
    return groups


def render_changelog_section(
    version: str,
    day: date,
    groups: dict[str, list[str]],
    summary: str | None,
) -> str:
    lines = [f"## [{version}] - {day.isoformat()}", ""]
    if summary:
        lines.append(summary.strip())
        lines.append("")
    order = ["新增", "修复", "变更", "重构", "性能", "文档", "测试", "杂项", "其他"]
    for title in order:
        items = groups.get(title)
        if not items:
            continue
        lines.append(f"### {title}")
        lines.append("")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
    if len(lines) == 2 and not summary:
        lines.append("- （无归类提交说明，请手工补充）")
        lines.append("")
    return "\n".join(lines)


def update_changelog(version: str, section: str) -> None:
    header = "# 变更日志"
    if CHANGELOG_FILE.is_file():
        existing = _read_text(CHANGELOG_FILE)
    else:
        existing = (
            f"{header}\n\n"
            "本文件由 `python scripts/release.py bump` 自动追加条目。\n"
            "版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。\n\n"
            "## [未发布]\n"
        )

    # 去掉旧的「未发布」占位，插入新版本后再放回空「未发布」
    body = existing
    if not body.lstrip().startswith("#"):
        body = header + "\n\n" + body

    # 在第一个 ## [ 之前插入；若有 ## [未发布] 则替换其内容为新节 + 空未发布
    unreleased = re.search(r"^## \[未发布\][^\n]*\n(?:(?!^## \[).*\n?)*", body, flags=re.M)
    new_block = "## [未发布]\n\n" + section
    if unreleased:
        body = body[: unreleased.start()] + new_block + body[unreleased.end() :]
    else:
        # 插在标题段落后第一个版本节之前
        m = re.search(r"^## \[", body, flags=re.M)
        if m:
            body = body[: m.start()] + new_block + body[m.start() :]
        else:
            body = body.rstrip() + "\n\n" + new_block

    _write_text(CHANGELOG_FILE, body if body.endswith("\n") else body + "\n")


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------


def cmd_status(_: argparse.Namespace) -> int:
    version = read_version()
    print(f"VERSION 文件: {version}")
    tag = latest_tag() if git_ok() else None
    print(f"最近 tag    : {tag or '(无)'}")
    if git_ok():
        print(f"工作区干净  : {'是' if not git_dirty() else '否'}")
    print()
    print("各文件版本探测：")
    ok = True
    for hit in collect_version_hits(version):
        rel = hit.path.relative_to(ROOT).as_posix() if hit.path.is_absolute() else str(hit.path)
        match = hit.found in hit.expected_forms
        mark = "OK" if match else "MISMATCH"
        if not match:
            ok = False
        print(f"  [{mark:8}] {rel}: found={hit.found!r} expect={list(hit.expected_forms)}")
    return 0 if ok else 1


def cmd_preview(_: argparse.Namespace) -> int:
    tag = latest_tag()
    subjects = commits_since(tag)
    print(f"自 {tag or '初始提交'} 以来共 {len(subjects)} 条提交：")
    groups = classify_commits(subjects)
    for title, items in groups.items():
        print(f"\n### {title}")
        for item in items:
            print(f"- {item}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    version = read_version()
    if args.dry_run:
        print(f"[dry-run] 将同步版本 {version} 到各目标文件")
        for hit in collect_version_hits(version):
            rel = hit.path.relative_to(ROOT).as_posix()
            if hit.found not in hit.expected_forms:
                print(f"  将修复 {rel}: {hit.found!r} -> {hit.expected_forms[0]!r}")
        return 0
    touched = apply_version(version)
    print(f"已同步版本 {version}：")
    for p in touched:
        print(f"  - {p}")
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    if not git_ok():
        print("错误：当前目录不是 git 仓库", file=sys.stderr)
        return 2

    current = read_version()
    try:
        new_version = bump_semver(current, args.part)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2

    if parse_semver(new_version) <= parse_semver(current) and args.part not in (
        "major",
        "minor",
        "patch",
    ):
        # 显式指定的版本必须严格大于当前
        if parse_semver(new_version) < parse_semver(current):
            print(f"错误：目标版本 {new_version} 低于当前 {current}", file=sys.stderr)
            return 2
        if new_version == current:
            print(f"错误：目标版本与当前相同 ({current})", file=sys.stderr)
            return 2

    tag = f"{TAG_PREFIX}{new_version}"
    if tag_exists(tag) and not args.no_tag:
        print(f"错误：tag {tag} 已存在", file=sys.stderr)
        return 2

    if git_dirty() and not args.allow_dirty and not args.dry_run:
        print("错误：工作区有未提交改动。请先提交/暂存，或加 --allow-dirty。", file=sys.stderr)
        print("提示：可先 `python scripts/release.py status` 查看状态。", file=sys.stderr)
        return 2

    prev_tag = latest_tag()
    subjects = commits_since(prev_tag)
    groups = classify_commits(subjects)
    section = render_changelog_section(new_version, date.today(), groups, args.message)

    print(f"{current} → {new_version}  (tag {tag})")
    print(f"相对 {prev_tag or '初始'} 的提交数: {len(subjects)}")

    if args.dry_run:
        print("\n[dry-run] CHANGELOG 新节预览：\n")
        print(section)
        print("[dry-run] 将更新的文件目标与 status 探测一致；不写盘、不提交、不打 tag。")
        return 0

    touched = apply_version(new_version)
    update_changelog(new_version, section)
    touched.append("CHANGELOG.md")

    print("已更新：")
    for p in touched:
        print(f"  - {p}")

    if args.no_commit:
        print("已跳过 commit（--no-commit）。请手工提交后打 tag。")
        return 0

    files_to_add = [str(ROOT / p) for p in touched if (ROOT / p).exists()]
    run_git("add", "--", *files_to_add)
    msg = f"chore(release): v{new_version}"
    if args.message:
        msg += f"\n\n{args.message.strip()}"
    run_git("commit", "-m", msg)
    print(f"已提交: {msg.splitlines()[0]}")

    if args.no_tag:
        print("已跳过 tag（--no-tag）。")
        return 0

    tag_msg = f"Vibe-Astock v{new_version}"
    if args.message:
        tag_msg += f"\n\n{args.message.strip()}"
    run_git("tag", "-a", tag, "-m", tag_msg)
    print(f"已打 tag: {tag}")
    print("推送示例: git push && git push origin " + tag)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="release.py",
        description="推进版本、同步代码版本号、写 CHANGELOG、打 git tag",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="显示 VERSION 与各文件是否一致")
    sub.add_parser("preview", help="预览自上次 tag 以来的提交归类")

    p_sync = sub.add_parser("sync", help="把 VERSION 同步到各代码/文档目标（不 bump）")
    p_sync.add_argument("--dry-run", action="store_true")

    p_bump = sub.add_parser("bump", help="推进版本并写 CHANGELOG / 提交 / 打 tag")
    p_bump.add_argument(
        "part",
        help="patch | minor | major | 或显式 x.y.z",
    )
    p_bump.add_argument("--dry-run", action="store_true")
    p_bump.add_argument("--no-commit", action="store_true")
    p_bump.add_argument("--no-tag", action="store_true")
    p_bump.add_argument("--allow-dirty", action="store_true")
    p_bump.add_argument("-m", "--message", default=None, help="发布摘要，写入 CHANGELOG 与 tag")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "preview":
        return cmd_preview(args)
    if args.command == "sync":
        return cmd_sync(args)
    if args.command == "bump":
        return cmd_bump(args)
    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
