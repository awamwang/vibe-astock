"""云空间文件：上传、下载、列出文件夹。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import LarkConfig
from .errors import raise_if_failed

# 整文件上传上限。更大的文件要走分片，本模块不处理。
UPLOAD_ALL_MAX_BYTES = 20 * 1024 * 1024


class DriveStore:
    """把项目文件保存到配置的云空间文件夹。"""

    def __init__(self, client: Any, config: LarkConfig) -> None:
        self._client = client
        self._config = config

    def upload(self, path: str | Path, *, file_name: str | None = None) -> str:
        """上传本地文件到云空间文件夹，返回 file_token。"""
        from lark_oapi.api.drive.v1 import UploadAllFileRequest, UploadAllFileRequestBody

        file_path = Path(path)
        size = file_path.stat().st_size
        if size > UPLOAD_ALL_MAX_BYTES:
            raise ValueError(f"{file_path.name} 超过 20MB，当前只支持整文件上传")

        name = file_name or file_path.name
        with file_path.open("rb") as handle:
            request = (
                UploadAllFileRequest.builder()
                .request_body(
                    UploadAllFileRequestBody.builder()
                    .file_name(name)
                    .parent_type("explorer")
                    .parent_node(self._config.drive_folder_token)
                    .size(size)
                    .file(handle)
                    .build()
                )
                .build()
            )
            response = self._client.drive.v1.file.upload_all(request)
        raise_if_failed(response, "上传文件")
        token = getattr(getattr(response, "data", None), "file_token", None)
        if not token:
            raise ValueError("上传文件成功但没有返回 file_token")
        return str(token)

    def download(self, file_token: str, dest: str | Path) -> Path:
        """按 file_token 下载云空间文件到本地路径。"""
        from lark_oapi.api.drive.v1 import DownloadFileRequest

        request = DownloadFileRequest.builder().file_token(file_token).build()
        response = self._client.drive.v1.file.download(request)
        raise_if_failed(response, "下载文件")
        payload = getattr(response, "file", None)
        if payload is None:
            raise ValueError("下载文件成功但没有文件内容")
        target = Path(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = payload.read() if hasattr(payload, "read") else bytes(payload)
        target.write_bytes(data)
        return target

    def list_files(self, *, page_size: int = 200) -> list[dict[str, str]]:
        """列出配置文件夹下的直接子文件。"""
        from lark_oapi.api.drive.v1 import ListFileRequest

        request = (
            ListFileRequest.builder()
            .folder_token(self._config.drive_folder_token)
            .page_size(page_size)
            .build()
        )
        response = self._client.drive.v1.file.list(request)
        raise_if_failed(response, "列出云空间文件")
        files = getattr(getattr(response, "data", None), "files", None) or []
        out: list[dict[str, str]] = []
        for item in files:
            out.append(
                {
                    "name": str(getattr(item, "name", "") or ""),
                    "token": str(getattr(item, "token", "") or ""),
                    "type": str(getattr(item, "type", "") or ""),
                }
            )
        return out
