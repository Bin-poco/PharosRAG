"""MinerU 在线精准解析 API 的单文档客户端。

原有 ``pharos parse`` 面向离线 CSV 批处理；上传链路需要的是可复用的单文件能力：
申请预签名地址 -> 上传 -> 轮询 -> 下载并安全解压 -> 定位 content_list/layout。
"""
from __future__ import annotations

import json
import os
import stat
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx


class MinerUError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MinerUResult:
    batch_id: str
    content_list_path: Path
    layout_path: Path | None
    content_root: Path


class MinerUClient:
    """同步客户端；由 FastAPI BackgroundTasks 在线程池中调用。"""

    def __init__(self, *, token: str, base_url: str = "https://mineru.net",
                 model_version: str = "vlm", language: str = "ch",
                 poll_seconds: float = 5.0, timeout_seconds: float = 1800.0,
                 max_archive_bytes: int = 512 * 1024 * 1024,
                 max_extract_bytes: int = 1024 * 1024 * 1024,
                 client_factory=None, sleep=time.sleep, monotonic=time.monotonic):
        self.token = (token or "").strip()
        self.base_url = base_url.rstrip("/")
        self.model_version = model_version
        self.language = language
        self.poll_seconds = max(0.0, float(poll_seconds))
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_archive_bytes = max(1, int(max_archive_bytes))
        self.max_extract_bytes = max(1, int(max_extract_bytes))
        self._client_factory = client_factory or (lambda: httpx.Client(follow_redirects=True))
        self._sleep = sleep
        self._monotonic = monotonic

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    @staticmethod
    def _api_json(response: httpx.Response, operation: str) -> dict:
        try:
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            raise MinerUError("mineru_unavailable", f"MinerU {operation} 请求失败。") from exc
        if not isinstance(data, dict) or data.get("code") != 0:
            raise MinerUError("mineru_rejected", f"MinerU {operation} 未接受请求。")
        return data

    @staticmethod
    def _https_url(value: str, label: str) -> str:
        parsed = urlparse(value or "")
        if parsed.scheme != "https" or not parsed.netloc:
            raise MinerUError("mineru_bad_response", f"MinerU 返回了非法的 {label} URL。")
        return value

    def _download_archive(self, client: httpx.Client, url: str, target: Path) -> None:
        url = self._https_url(url, "结果下载")
        total = 0
        try:
            with client.stream("GET", url, timeout=httpx.Timeout(600.0, connect=10.0)) as response:
                response.raise_for_status()
                with open(target, "xb") as out:
                    for chunk in response.iter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > self.max_archive_bytes:
                            raise MinerUError("mineru_archive_too_large", "MinerU 结果压缩包超过安全限制。")
                        out.write(chunk)
        except MinerUError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise MinerUError("mineru_download_failed", "下载 MinerU 解析结果失败。") from exc

    def _safe_extract(self, archive: Path, dest: Path) -> None:
        """拒绝 Zip Slip、符号链接、文件数炸弹和超量解压。"""
        dest = dest.resolve()
        try:
            with zipfile.ZipFile(archive) as bundle:
                members = bundle.infolist()
                if len(members) > 10_000:
                    raise MinerUError("mineru_archive_unsafe", "MinerU 结果文件数超过安全限制。")
                expanded = sum(item.file_size for item in members)
                if expanded > self.max_extract_bytes:
                    raise MinerUError("mineru_archive_too_large", "MinerU 解压结果超过安全限制。")
                for item in members:
                    mode = item.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise MinerUError("mineru_archive_unsafe", "MinerU 结果包含不允许的符号链接。")
                    target = (dest / item.filename).resolve()
                    if not target.is_relative_to(dest):
                        raise MinerUError("mineru_archive_unsafe", "MinerU 结果包含越界路径。")
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(item) as source, open(target, "xb") as output:
                        while chunk := source.read(1024 * 1024):
                            output.write(chunk)
        except MinerUError:
            raise
        except (OSError, zipfile.BadZipFile) as exc:
            raise MinerUError("mineru_bad_archive", "MinerU 返回的结果不是有效压缩包。") from exc

    @staticmethod
    def _find_outputs(dest: Path, batch_id: str) -> MinerUResult:
        content_paths = sorted(
            p for p in dest.rglob("*content_list.json") if "_v2" not in p.name)
        if not content_paths:
            raise MinerUError("mineru_output_missing", "MinerU 结果缺少 content_list.json。")
        content_path = content_paths[0]
        try:
            content = json.loads(content_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MinerUError("mineru_output_invalid", "MinerU content_list.json 无法读取。") from exc
        if not isinstance(content, list) or not content:
            raise MinerUError("mineru_output_invalid", "MinerU content_list.json 内容为空或格式错误。")
        layout_path = next(iter(content_path.parent.rglob("layout.json")), None)
        if layout_path is None:
            layout_path = next(iter(dest.rglob("layout.json")), None)
        return MinerUResult(batch_id=batch_id, content_list_path=content_path,
                            layout_path=layout_path, content_root=content_path.parent)

    def parse_pdf(self, source: Path, dest: Path, *, data_id: str) -> MinerUResult:
        if not self.token:
            raise MinerUError("mineru_unconfigured", "未配置 MinerU API Token。")
        dest.mkdir(parents=True, exist_ok=True)
        deadline = self._monotonic() + self.timeout_seconds
        upload_name = source.name
        body = {
            "files": [{"name": upload_name, "data_id": data_id}],
            "model_version": self.model_version,
            "enable_formula": True,
            "enable_table": True,
        }
        if self.language:
            body["language"] = self.language

        with self._client_factory() as client:
            response = client.post(f"{self.base_url}/api/v4/file-urls/batch",
                                   headers=self._headers(), json=body, timeout=60.0)
            submitted = self._api_json(response, "提交")
            payload = submitted.get("data") or {}
            batch_id = str(payload.get("batch_id") or "")
            urls = payload.get("file_urls") or []
            if not batch_id or len(urls) != 1:
                raise MinerUError("mineru_bad_response", "MinerU 提交响应缺少 batch_id/file_url。")

            upload_url = self._https_url(str(urls[0]), "上传")
            try:
                # 预签名上传明确不能携带 MinerU Authorization/Content-Type。
                uploaded = client.put(upload_url, content=source.read_bytes(), timeout=600.0)
                uploaded.raise_for_status()
            except (httpx.HTTPError, OSError) as exc:
                raise MinerUError("mineru_upload_failed", "上传 PDF 到 MinerU 失败。") from exc

            zip_url = ""
            while self._monotonic() < deadline:
                try:
                    response = client.get(
                        f"{self.base_url}/api/v4/extract-results/batch/{batch_id}",
                        headers=self._headers(), timeout=60.0)
                    polled = self._api_json(response, "轮询")
                except MinerUError as exc:
                    if exc.code not in {"mineru_unavailable"}:
                        raise
                    self._sleep(self.poll_seconds)
                    continue
                rows = (polled.get("data") or {}).get("extract_result") or []
                row = next((item for item in rows if item.get("data_id") == data_id), None)
                if row is None and len(rows) == 1:
                    row = rows[0]
                state = str((row or {}).get("state") or "").lower()
                if state == "failed":
                    raise MinerUError("mineru_parse_failed", "MinerU 无法解析该 PDF。")
                if state == "done":
                    zip_url = str(row.get("full_zip_url") or "")
                    if not zip_url:
                        raise MinerUError("mineru_bad_response", "MinerU 完成响应缺少结果下载地址。")
                    break
                self._sleep(self.poll_seconds)
            if not zip_url:
                raise MinerUError("mineru_timeout", "等待 MinerU 解析超时。")

            archive = dest / ".mineru-result.zip.tmp"
            try:
                self._download_archive(client, zip_url, archive)
                self._safe_extract(archive, dest)
            finally:
                try:
                    os.remove(archive)
                except FileNotFoundError:
                    pass
        return self._find_outputs(dest, batch_id)
