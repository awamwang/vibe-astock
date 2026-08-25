"""本机数据备份 / 导入。

打包 `~/.duanxian-agents/` 里已经落到磁盘的数据（请求缓存 + 复盘/热度等生成物），
不含日志。导入时接受本模块打的 zip，或一份解压后的文件夹 / 原始数据目录。
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable, Optional

from .util import china_now

FORMAT_ID = "vibe-astock-backup"
ARCHIVE_VERSION = 1
DATA_ROOT = os.path.expanduser("~/.duanxian-agents")

SKIP_DIR_NAMES = frozenset({"logs", "log", "__pycache__", ".git"})
SKIP_FILE_NAMES = frozenset({".ds_store", "thumbs.db"})
SKIP_SUFFIXES = (".log", ".tmp", ".pyc", ".pyo")

# 防 zip 炸弹：单文件 / 总解压量 / 文件数
MAX_MEMBER_BYTES = 200 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBER_COUNT = 50_000
MAX_UPLOAD_BYTES = 400 * 1024 * 1024


class BackupError(ValueError):
    """备份或导入无法继续。"""


def _norm(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_skipped_dir(name: str) -> bool:
    return name.lower() in SKIP_DIR_NAMES or name.startswith(".")


def _is_skipped_file(name: str) -> bool:
    lower = name.lower()
    if lower in SKIP_FILE_NAMES or lower.startswith("."):
        return True
    if lower.endswith(".log.gz") or lower.endswith(".log.1"):
        return True
    return any(lower.endswith(suf) for suf in SKIP_SUFFIXES)


def _iter_files(root: Path) -> Iterable[Path]:
    """遍历数据根下应纳入备份的文件。跳过日志目录、隐藏目录和临时文件。"""
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _is_skipped_dir(d)]
        for name in filenames:
            if _is_skipped_file(name):
                continue
            yield Path(dirpath) / name


def _count_skipped_logs(root: Path) -> int:
    if not root.is_dir():
        return 0
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        skipped_here = [d for d in dirnames if _is_skipped_dir(d)]
        dirnames[:] = [d for d in dirnames if d not in skipped_here]
        for d in skipped_here:
            for _dir, _sub, files in os.walk(Path(dirpath) / d):
                n += len(files)
        n += sum(1 for name in filenames if _is_skipped_file(name))
    return n


def overview(root: Optional[str] = None) -> dict[str, Any]:
    """当前可备份数据的规模：目录、文件数、字节数。"""
    base = _norm(root or DATA_ROOT)
    folders: dict[str, dict[str, int]] = {}
    total_files = 0
    total_bytes = 0
    for path in _iter_files(base):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        rel = path.relative_to(base).as_posix()
        top = rel.split("/", 1)[0] if "/" in rel else rel
        bucket = folders.setdefault(top, {"files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += size
        total_files += 1
        total_bytes += size

    series_info: dict[str, Any]
    try:
        from . import series_store as store

        db_path = str(base / "cache" / "series.db")
        series_info = store.overview(path=db_path)
    except Exception:  # noqa: BLE001
        series_info = {
            "db_path": str(base / "cache" / "series.db"),
            "byte_count": 0,
            "series": [],
            "total_days": 0,
        }

    return {
        "root": str(base),
        "cache_dir": str(base / "cache"),
        "exists": base.is_dir(),
        "file_count": total_files,
        "byte_count": total_bytes,
        "skipped_logs": _count_skipped_logs(base) if base.is_dir() else 0,
        "folders": [
            {"name": name, "files": info["files"], "bytes": info["bytes"]}
            for name, info in sorted(folders.items())
        ],
        "series": series_info,
    }


def _archive_name() -> str:
    return f"duanxian-agents-{china_now().strftime('%Y%m%d-%H%M%S')}.zip"


def _write_zip(zf: zipfile.ZipFile, root: Path) -> dict[str, Any]:
    files = []
    total_bytes = 0
    for path in _iter_files(root):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        zf.write(path, f"data/{rel}")
        files.append(rel)
        total_bytes += size
    skipped = _count_skipped_logs(root) if root.is_dir() else 0
    manifest = {
        "format": FORMAT_ID,
        "version": ARCHIVE_VERSION,
        "created_at": china_now().strftime("%Y-%m-%d %H:%M:%S") + " CST",
        "source": str(root),
        "file_count": len(files),
        "byte_count": total_bytes,
        "skipped_logs": skipped,
    }
    zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def build_zip_bytes(root: Optional[str] = None) -> tuple[bytes, dict[str, Any]]:
    """在内存里打一份备份 zip。"""
    base = _norm(root or DATA_ROOT)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = _write_zip(zf, base)
    return buf.getvalue(), manifest


def write_zip_file(zip_path: str | Path, root: Optional[str] = None) -> dict[str, Any]:
    """把备份 zip 写到指定文件路径。"""
    target = Path(zip_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            manifest = _write_zip(zf, _norm(root or DATA_ROOT))
        os.replace(tmp, target)
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(f"写出备份失败：{exc}") from exc
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "ok": True,
        "path": str(target.resolve()),
        "filename": target.name,
        **manifest,
    }


def export_to_dir(dest_dir: str, root: Optional[str] = None) -> dict[str, Any]:
    """把备份 zip 写到指定目录，返回写入路径与清单。"""
    dest = _resolve_dest_dir(dest_dir)
    base = _norm(root or DATA_ROOT)
    if dest == base or base in dest.parents:
        raise BackupError("导出目录不能落在数据根目录内部")
    dest.mkdir(parents=True, exist_ok=True)
    return write_zip_file(dest / _archive_name(), root=str(base))


def export_series_json(dest_dir: str, root: Optional[str] = None) -> dict[str, Any]:
    """导出长序列为可读 JSON 目录（从 series.db 抽出）。"""
    dest = _resolve_dest_dir(dest_dir)
    base = _norm(root or DATA_ROOT)
    if dest == base or base in dest.parents:
        raise BackupError("导出目录不能落在数据根目录内部")
    from . import series_store as store

    db_path = str(base / "cache" / "series.db")
    try:
        return store.export_json_bundle(str(dest), path=db_path)
    except ValueError as exc:
        raise BackupError(str(exc)) from exc
    except OSError as exc:
        raise BackupError(f"导出长序列失败：{exc}") from exc


def _resolve_dest_dir(raw: str) -> Path:
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        raise BackupError("请填写导出目录")
    dest = Path(text).expanduser()
    if not dest.is_absolute():
        dest = Path.home() / dest
    try:
        dest = dest.resolve()
    except OSError as exc:
        raise BackupError(f"无法解析导出目录：{exc}") from exc
    if dest.exists() and not dest.is_dir():
        raise BackupError(f"导出路径不是目录：{dest}")
    return dest


def _resolve_import_path(raw: str) -> Path:
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        raise BackupError("请填写要导入的压缩包或文件夹路径")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = Path.home() / path
    try:
        path = path.resolve()
    except OSError as exc:
        raise BackupError(f"无法解析导入路径：{exc}") from exc
    if not path.exists():
        raise BackupError(f"路径不存在：{path}")
    return path


def _safe_zip_member(name: str) -> str:
    """拒绝 zip 内的绝对路径和 `..` 穿越。返回规范化的 posix 相对路径。"""
    raw = (name or "").replace("\\", "/").strip()
    if not raw or raw.endswith("/"):
        return ""
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise BackupError(f"压缩包内含绝对路径，已拒绝：{name}")
    parts = [p for p in raw.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        raise BackupError(f"压缩包内含越界路径，已拒绝：{name}")
    return "/".join(parts)


def _extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    dest_res = dest.resolve()
    total = 0
    count = 0
    for info in zf.infolist():
        rel = _safe_zip_member(info.filename)
        if not rel:
            continue
        count += 1
        if count > MAX_MEMBER_COUNT:
            raise BackupError("压缩包文件数超过上限")
        size = info.file_size
        if size > MAX_MEMBER_BYTES:
            raise BackupError(f"压缩包内单文件过大：{rel}")
        total += size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise BackupError("压缩包解压体积超过上限")
        target = (dest / rel).resolve()
        if dest_res not in target.parents and target != dest_res:
            raise BackupError(f"压缩包内含越界路径，已拒绝：{rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with zf.open(info, "r") as src, open(target, "wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_MEMBER_BYTES:
                    raise BackupError(f"压缩包内单文件过大：{rel}")
                out.write(chunk)


def _payload_root(extracted: Path) -> Path:
    """识别备份包布局：带 manifest + data/，或原始 duanxian-agents 目录。"""
    data = extracted / "data"
    manifest = extracted / "manifest.json"
    if data.is_dir() and (manifest.is_file() or (data / "cache").exists()
                          or (data / "reviews").exists()):
        return data
    return extracted


def _copy_payload(src_root: Path, dest_root: Path) -> dict[str, Any]:
    imported = 0
    bytes_copied = 0
    dest_root.mkdir(parents=True, exist_ok=True)
    for path in _iter_files(src_root):
        rel = path.relative_to(src_root)
        target = dest_root / rel
        resolved = target.resolve()
        if dest_root.resolve() not in resolved.parents and resolved != dest_root.resolve():
            raise BackupError(f"导入路径越界：{rel.as_posix()}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        imported += 1
        try:
            bytes_copied += path.stat().st_size
        except OSError:
            pass
    skipped = _count_skipped_logs(src_root)
    return {
        "ok": True,
        "imported": imported,
        "byte_count": bytes_copied,
        "skipped_logs": skipped,
        "root": str(dest_root),
    }


def import_from_dir(src: Path, dest_root: Optional[str] = None) -> dict[str, Any]:
    payload = _payload_root(src)
    dest = _norm(dest_root or DATA_ROOT)
    if payload.resolve() == dest:
        raise BackupError("导入源不能是当前正在使用的数据目录本身")
    return _copy_payload(payload, dest)


def import_from_zip_file(zip_path: Path, dest_root: Optional[str] = None) -> dict[str, Any]:
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile as exc:
        raise BackupError("不是有效的 zip 压缩包") from exc
    with zf, tempfile.TemporaryDirectory(prefix="vibe-backup-") as tmp:
        _extract_zip(zf, Path(tmp))
        return import_from_dir(Path(tmp), dest_root=dest_root)


def import_from_zip_bytes(data: bytes, dest_root: Optional[str] = None) -> dict[str, Any]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise BackupError("上传的压缩包过大，请改为填写本机路径导入")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data), "r")
    except zipfile.BadZipFile as exc:
        raise BackupError("不是有效的 zip 压缩包") from exc
    with zf, tempfile.TemporaryDirectory(prefix="vibe-backup-") as tmp:
        _extract_zip(zf, Path(tmp))
        return import_from_dir(Path(tmp), dest_root=dest_root)


def import_from_path(raw: str, dest_root: Optional[str] = None) -> dict[str, Any]:
    """从本机 zip 或文件夹导入。"""
    path = _resolve_import_path(raw)
    if path.is_dir():
        return import_from_dir(path, dest_root=dest_root)
    if path.suffix.lower() != ".zip":
        raise BackupError("文件必须是 .zip 压缩包，或改填文件夹路径")
    return import_from_zip_file(path, dest_root=dest_root)


def import_from_base64(blob: str, dest_root: Optional[str] = None) -> dict[str, Any]:
    text = (blob or "").strip()
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    if not text:
        raise BackupError("压缩包内容为空")
    try:
        data = base64.b64decode(text, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise BackupError("压缩包内容无法解码") from exc
    if not data:
        raise BackupError("压缩包内容为空")
    return import_from_zip_bytes(data, dest_root=dest_root)


def _reveal_dir(path: Path) -> None:
    """用系统文件管理器打开目录。"""
    target = str(path)
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_data_dir(kind: str, root: Optional[str] = None) -> dict[str, Any]:
    """打开数据根目录、cache 或长序列库所在目录。目录不存在时先创建。"""
    key = (kind or "root").strip().lower()
    base = _norm(root or DATA_ROOT)
    mapping = {
        "root": base,
        "cache": base / "cache",
        "series": base / "cache",
    }
    if key not in mapping:
        raise BackupError("只能打开数据根目录、cache 或长序列目录")
    path = mapping[key]
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"无法创建目录：{exc}") from exc
    try:
        _reveal_dir(path)
    except OSError as exc:
        raise BackupError(f"无法打开目录：{exc}") from exc
    return {"ok": True, "path": str(path), "kind": key}
