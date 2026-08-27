"""持锁调用检测 —— 发现 with lock 块内再调会抢同一把锁的函数（非可重入 Lock 会自死锁）。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class LockViolation:
    path: str
    function: str
    line: int
    lock: str
    callee: str


def _repo_root() -> Path:
    here = Path(__file__).resolve().parent
    return here.parent


def _iter_py_files(paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for base in paths:
        if base.is_file() and base.suffix == ".py":
            out.append(base)
            continue
        if base.is_dir():
            out.extend(sorted(base.rglob("*.py")))
    return out


def _lock_targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Tuple):
        names: list[str] = []
        for elt in node.elts:
            names.extend(_lock_targets(elt))
        return names
    return []


def _call_name(node: ast.Call) -> str | None:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


class _FunctionLockUse(ast.NodeVisitor):
    def __init__(self) -> None:
        self.locks: set[str] = set()

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            for lock in _lock_targets(item.context_expr):
                if lock.endswith("lock") or lock.endswith("Lock") or lock.endswith("_LOCK"):
                    self.locks.add(lock)
        self.generic_visit(node)


class _LockHoldVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        path: str,
        function: str,
        lock_users: dict[str, set[str]],
    ) -> None:
        self.path = path
        self.function = function
        self.lock_users = lock_users
        self.violations: list[LockViolation] = []
        self._lock_stack: list[str] = []

    def visit_With(self, node: ast.With) -> None:
        held: list[str] = []
        for item in node.items:
            held.extend(_lock_targets(item.context_expr))
        self._lock_stack.extend(held)
        try:
            self.generic_visit(node)
        finally:
            for _ in held:
                self._lock_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        callee = _call_name(node)
        if callee and self._lock_stack:
            for lock in self._lock_stack:
                users = self.lock_users.get(lock)
                if users and callee in users:
                    self.violations.append(
                        LockViolation(
                            path=self.path,
                            function=self.function,
                            line=node.lineno,
                            lock=lock,
                            callee=callee,
                        )
                    )
        self.generic_visit(node)


def _analyze_module(path: Path, source: str) -> list[LockViolation]:
    rel = str(path.relative_to(_repo_root())).replace("\\", "/")
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError:
        return []

    lock_users: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        usage = _FunctionLockUse()
        usage.visit(node)
        for lock in usage.locks:
            lock_users.setdefault(lock, set()).add(node.name)

    violations: list[LockViolation] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        visitor = _LockHoldVisitor(path=rel, function=node.name, lock_users=lock_users)
        visitor.visit(node)
        violations.extend(visitor.violations)
    return violations


def scan_paths(paths: Iterable[Path | str]) -> list[LockViolation]:
    bases = [Path(p) if isinstance(p, str) else p for p in paths]
    violations: list[LockViolation] = []
    for path in _iter_py_files(bases):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        violations.extend(_analyze_module(path, source))
    return violations


def default_scan_paths() -> list[Path]:
    root = _repo_root()
    return [
        root / "duanxian",
        root / "plugins",
        root / "vr",
        root / "server.py",
    ]


def format_violations(violations: Iterable[LockViolation]) -> str:
    lines = [
        f"{v.path}:{v.line} {v.function}() 持 {v.lock} 时调用 {v.callee}()（会再次抢锁）"
        for v in violations
    ]
    return "\n".join(lines)
