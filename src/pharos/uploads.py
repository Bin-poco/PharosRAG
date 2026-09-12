"""文档上传的第一版竖向闭环。

边界刻意很小:
  - 身份仍由 service 的 X-API-Key middleware 给出，本模块不信任客户端 tenant;
  - Markdown 本地标准化，PDF 交给 MinerU，再复用 Chunker + Embedder 现有建库链;
  - 任务记录按文档原子写 JSON，便于本地开发;后续换 PostgreSQL/Celery 时 API 形状不变。

BackgroundTasks 只是本地版执行器：进程重启不保证任务继续，所以不伪装成生产队列。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from embedder import Embedder

from .ingestion import IngestionPipeline, UploadError
from .mineru import MinerUClient, MinerUError

log = logging.getLogger("pharos")

ALLOWED_SUFFIXES = {".md", ".markdown", ".pdf"}
ACCESS_SCOPES = {"private", "restricted", "tenant"}


def personal_principal(identity) -> str:
    """个人 principal 由服务端身份派生，绝不接受表单传入。"""
    return f"user:{identity.name}"


def can_upload(identity) -> bool:
    return bool(identity and identity.tenant and
                (identity.admin or "uploader" in set(identity.roles or [])))


def build_upload_acl(identity, access_scope: str, groups: list[str]) -> dict:
    """产品层三种范围 -> 引擎层既有 ACL。tenant 永远取认证身份。"""
    if not can_upload(identity):
        raise UploadError("upload_forbidden", "当前身份没有 uploader 或 admin 权限。")
    scope = (access_scope or "private").strip().lower()
    if scope not in ACCESS_SCOPES:
        raise UploadError("bad_access_scope", "access_scope 必须是 private|restricted|tenant。")
    requested = list(dict.fromkeys(g.strip() for g in groups if g and g.strip()))
    own_groups = set(identity.principals or [])
    if scope == "private" and requested:
        raise UploadError("groups_not_allowed", "private 文档不能指定 groups。")
    if scope == "restricted":
        if not requested:
            raise UploadError("groups_required", "restricted 文档至少指定一个 group。")
        outside = sorted(set(requested) - own_groups)
        if outside and not identity.admin:
            raise UploadError("group_forbidden", f"不能授权给当前身份不属于的 group:{', '.join(outside)}")
    if scope == "tenant" and not identity.admin:
        raise UploadError("tenant_publish_forbidden", "只有 admin 可以发布 tenant 内公开文档。")

    allow = [] if scope == "tenant" else [personal_principal(identity), *requested]
    return {
        "tenant": identity.tenant,
        "allow": list(dict.fromkeys(allow)),
        "visibility": "public" if scope == "tenant" else "restricted",
        "unset": False,
    }


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class DocumentUploadManager:
    """持久化上传记录并复用现有引擎建立单篇 Markdown/PDF 索引。"""

    def __init__(self, root: str, retriever, max_bytes: int = 10 * 1024 * 1024,
                 mineru_client: MinerUClient | None = None):
        self.root = Path(root).expanduser().resolve()
        self.retriever = retriever
        self.max_bytes = max(1, int(max_bytes))
        self.mineru_client = mineru_client
        self._lock = threading.RLock()
        self._pipeline = None
        self.root.mkdir(parents=True, exist_ok=True)

    def _doc_dir(self, doc_id: str) -> Path:
        # doc_id 完全由服务端生成;仍用 resolve 不变量防未来调用方误传。
        path = (self.root / doc_id).resolve()
        if not path.is_relative_to(self.root):
            raise UploadError("invalid_doc_id", "非法 document id。")
        return path

    @staticmethod
    def _record_path(doc_dir: Path) -> Path:
        return doc_dir / "record.json"

    def _write_record(self, record: dict) -> None:
        doc_dir = self._doc_dir(record["document_id"])
        doc_dir.mkdir(parents=True, exist_ok=True)
        path = self._record_path(doc_dir)
        tmp = path.with_suffix(".json.tmp")
        data = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _read_record(self, document_id: str) -> dict | None:
        path = self._record_path(self._doc_dir(document_id))
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def create(self, stream: BinaryIO, *, filename: str, content_type: str | None,
               identity, access_scope: str, groups: list[str]) -> dict:
        scope = (access_scope or "private").strip().lower()
        normalized_groups = list(dict.fromkeys(g.strip() for g in groups if g and g.strip()))
        acl = build_upload_acl(identity, scope, normalized_groups)
        safe_name = Path((filename or "").replace("\\", "/")).name
        suffix = Path(safe_name).suffix.lower()
        if not safe_name or suffix not in ALLOWED_SUFFIXES:
            raise UploadError("unsupported_type", "当前支持 .md、.markdown 和 .pdf 文档。")

        document_id = f"upload__{uuid.uuid4().hex}"
        job_id = f"job_{uuid.uuid4().hex}"
        doc_dir = self._doc_dir(document_id)
        doc_dir.mkdir(parents=True, exist_ok=False)
        source = doc_dir / ("source" + suffix)
        digest = hashlib.sha256()
        size = 0
        signature = bytearray()
        try:
            with open(source, "xb") as out:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    if len(signature) < 1024:
                        signature.extend(chunk[:1024 - len(signature)])
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise UploadError("file_too_large", f"文件超过 {self.max_bytes} bytes 限制。")
                    digest.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise UploadError("empty_file", "上传文件为空。")
            if suffix == ".pdf" and b"%PDF-" not in signature:
                raise UploadError("invalid_pdf", "文件扩展名是 .pdf，但内容不是有效 PDF。")
            if (suffix == ".pdf" and
                    (self.mineru_client is None or
                     not getattr(self.mineru_client, "configured", True))):
                raise UploadError("mineru_unconfigured", "PDF 上传需要先配置 MinerU API Token。")
        except Exception:
            shutil.rmtree(doc_dir, ignore_errors=True)
            raise

        now = _utcnow()
        record = {
            "document_id": document_id,
            "job_id": job_id,
            "tenant": identity.tenant,
            "owner": identity.name,
            "filename": safe_name,
            "content_type": content_type or "application/octet-stream",
            "source_format": "pdf" if suffix == ".pdf" else "markdown",
            "size": size,
            "sha256": digest.hexdigest(),
            "access_scope": scope,
            "groups": normalized_groups,
            "acl": acl,
            "status": "queued",
            "stage": "uploaded",
            "chunk_count": 0,
            "error_code": None,
            "created_at": now,
            "updated_at": now,
            "source_path": str(source),
        }
        with self._lock:
            self._write_record(record)
        return self.public_record(record)

    def _update(self, document_id: str, **changes) -> dict:
        with self._lock:
            record = self._read_record(document_id)
            if record is None:
                raise UploadError("not_found", "文档任务不存在。")
            record.update(changes)
            record["updated_at"] = _utcnow()
            self._write_record(record)
            return record

    def _get_pipeline(self):
        with self._lock:
            if self._pipeline is None:
                self._pipeline = IngestionPipeline(
                    self.root,
                    self.retriever,
                    mineru_client=self.mineru_client,
                    # 保留 uploads.Embedder 这个替换点，兼容既有测试和调用方。
                    embedder_factory=lambda *args, **kwargs: Embedder(*args, **kwargs),
                )
            return self._pipeline

    def _claim(self, document_id: str) -> dict | None:
        """原子领取 queued 任务；重复调度不会并发重复建库。"""
        with self._lock:
            record = self._read_record(document_id)
            if record is None:
                raise UploadError("not_found", "文档任务不存在。")
            if record.get("status") != "queued":
                return None
            record.update(status="running", stage="parsing", error_code=None, updated_at=_utcnow())
            self._write_record(record)
            return record

    def process(self, document_id: str) -> None:
        """BackgroundTasks 入口。失败转持久化 failed，不把内部异常暴露给客户端。"""
        try:
            record = self._claim(document_id)
            if record is None:
                return
            stats = self._get_pipeline().run(
                record, lambda **changes: self._update(document_id, **changes))
            self._update(document_id, status="ready", stage="ready",
                         chunk_count=stats["chunk_count"],
                         parser_batch_id=stats.get("parser_batch_id"))
        except Exception as exc:
            code = exc.code if isinstance(exc, (UploadError, MinerUError)) else "index_failed"
            log.exception("upload processing failed: doc=%s code=%s", document_id, code)
            try:
                self._update(document_id, status="failed", stage="failed", error_code=code)
            except Exception:
                log.exception("upload failure state could not be persisted: doc=%s", document_id)

    def get_job(self, job_id: str) -> dict | None:
        # 第一版是文件记录，规模小;后续 PostgreSQL 换成索引查询。
        for path in self.root.glob("upload__*/record.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if record.get("job_id") == job_id:
                return self.public_record(record)
        return None

    @staticmethod
    def public_record(record: dict) -> dict:
        return {k: record.get(k) for k in (
            "document_id", "job_id", "tenant", "owner", "filename", "size", "sha256",
            "source_format", "access_scope", "groups", "status", "stage", "chunk_count",
            "parser_batch_id", "error_code",
            "created_at", "updated_at")}
