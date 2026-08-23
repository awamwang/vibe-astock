"""插件管理命令行：注册 / 卸载 / 启用 / 停用 / 列表。"""

from __future__ import annotations

import argparse
import sys

from . import plugin_store as ps


def _cmd_list(_args: argparse.Namespace) -> int:
    rows = ps.list_plugins()
    if not rows:
        print("（无已注册插件）")
        print(f"注册表：{ps.registry_file()}")
        return 0
    print(f"{'ID':<10} {'状态':<6} {'名称':<20} {'版本':<10} 路径")
    print("-" * 80)
    for r in rows:
        status = "启用" if r.enabled else "停用"
        print(f"{r.id:<10} {status:<6} {r.name:<20} {r.version:<10} {r.path}")
    print(f"\n共 {len(rows)} 个；注册表：{ps.registry_file()}")
    return 0


def _cmd_register(args: argparse.Namespace) -> int:
    try:
        rec = ps.register(args.path, enabled=not args.disabled)
    except (ValueError, TypeError, RuntimeError) as exc:
        print(f"注册失败：{exc}", file=sys.stderr)
        return 1
    state = "启用" if rec.enabled else "停用"
    print(f"✓ 已注册插件 {rec.name} v{rec.version}（id={rec.id}，{state}）")
    print("  若 server 正在运行，请重启后加载新插件。")
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    try:
        rec = ps.uninstall(args.plugin)
    except ValueError as exc:
        print(f"卸载失败：{exc}", file=sys.stderr)
        return 1
    print(f"✓ 已从注册表移除 {rec.name}（id={rec.id}）")
    print("  插件文件未删除；若 server 正在运行，请重启。")
    return 0


def _cmd_enable(args: argparse.Namespace) -> int:
    try:
        rec = ps.set_enabled(args.plugin, True)
    except ValueError as exc:
        print(f"启用失败：{exc}", file=sys.stderr)
        return 1
    print(f"✓ 已启用 {rec.name}（id={rec.id}）")
    print("  若 server 正在运行，请重启后生效。")
    return 0


def _cmd_disable(args: argparse.Namespace) -> int:
    try:
        rec = ps.set_enabled(args.plugin, False)
    except ValueError as exc:
        print(f"停用失败：{exc}", file=sys.stderr)
        return 1
    print(f"✓ 已停用 {rec.name}（id={rec.id}）")
    print("  若 server 正在运行，请重启后生效。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m duanxian.plugin_cli",
        description="管理 vibe-astock 钩子插件（注册表在用户目录 ~/.vibe-astock/plugins.json）",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出已注册插件").set_defaults(func=_cmd_list)

    reg = sub.add_parser("register", help="注册插件（.py 文件须导出 PACK）")
    reg.add_argument("path", help="插件 .py 路径")
    reg.add_argument("--disabled", action="store_true", help="注册后默认停用")
    reg.set_defaults(func=_cmd_register)

    un = sub.add_parser("uninstall", help="从注册表卸载（不删文件）")
    un.add_argument("plugin", help="插件 id / id 前缀 / 唯一名称")
    un.set_defaults(func=_cmd_uninstall)

    en = sub.add_parser("enable", help="启用插件")
    en.add_argument("plugin", help="插件 id / id 前缀 / 唯一名称")
    en.set_defaults(func=_cmd_enable)

    dis = sub.add_parser("disable", help="停用插件")
    dis.add_argument("plugin", help="插件 id / id 前缀 / 唯一名称")
    dis.set_defaults(func=_cmd_disable)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
