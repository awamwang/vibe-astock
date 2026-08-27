"""持锁调用静态扫描（CI / 本地：python scripts/check_lock_holds.py）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from duanxian.lock_safety_check import default_scan_paths, format_violations, scan_paths


def main() -> int:
    violations = scan_paths(default_scan_paths())
    if not violations:
        print("lock hold scan: OK")
        return 0
    print(format_violations(violations))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
