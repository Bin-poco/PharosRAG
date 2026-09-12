"""带 ACL 的 Markdown/PDF 文档上传与摄取编排。

边界刻意很小:
  - 身份仍由 service 的 X-API-Key middleware 给出，本模块不信任客户端 tenant;
  - Markdown 本地标准化，PDF 交给 MinerU，再复用 Chunker + Embedder 现有建库链;
  - PostgreSQL + Celery/Redis 提供可靠队列；未配置时保留 JSON + BackgroundTasks 本地兼容模式。

BackgroundTasks 只是兼容执行器：进程重启不保证任务继续，不用于生产可靠性承诺。
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from embedder import Embedder

from .ingestion import IngestionPipeline, UploadError, is_transient_ingestion_error
from .jobs import FileJobRepository
from .mineru import MinerUClient, MinerUError

log = logging.getLogger("pharos")

ALLOWED_SUFFIXES = {".md", ".markdown", ".pdf"}
ACCESS_SCOPES = {"private", "restricted", "tenant"}
MAX_FILENAME_CHARS = 512
MAX_CONTENT_TYPE_CHARS = 160


def personal_principal(identity) -> str:
    """个人 principal 由服务端身份派生，绝不接受表单传入。"""
    return f"user:{identity.name}"


def can_upload(identity) -> bool:
    return bool(identity and identity.tenant and
                (identity.admin or "uploader" in set(identity.roles or [])))


def build_upload_acl(identity, access_scope: str, groups: list[str], *,
                     owner: str | None = None) -> dict:
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

    owner_principal = f"user:{owner or identity.name}"
    allow = [] if scope == "tenant" else [owner_principal, *requested]
    return {
        "tenant": identity.tenant,
        "allow": list(dict.fromkeys(allow)),
        "visibility": "public" if scope == "tenant" else "restricted",
        "unset": False,
    }


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def retry_delay_seconds(attempt: int, job_id: str) -> int:
    """指数退避并加入稳定抖动，防止一批故障任务同时冲击外部服务。"""
    base = min(300, 10 * (3 ** max(0, int(attempt) - 1)))
    spread = max(1, base // 5)
    jitter = int(hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:8], 16) % spread
    return base + jitter


class DocumentUploadManager:
    """持久化上传记录并复用现有引擎建立单篇 Markdown/PDF 索引。"""

    def __init__(self, root: str, retriever, max_bytes: int = 10 * 1024 * 1024,
                 mineru_client: MinerUClient | None = None, repository=None,
                 max_attempts: int = 3):
        self.root = Path(root).expanduser().resolve()
        self.retriever = retriever
        self.max_bytes = max(1, int(max_bytes))
        self.mineru_client = mineru_client
        self.max_attempts = max(1, int(max_attempts))
        self._lock = threading.RLock()
        self._pipeline = None
        self.root.mkdir(parents=True, exist_ok=True)
        self.repository = repository or FileJobRepository(self.root)

    def _doc_dir(self, doc_id: str) -> Path:
        # doc_id 完全由服务端生成;仍用 resolve 不变量防未来调用方误传。
        path = (self.root / doc_id).resolve()
        if not path.is_relative_to(self.root):
            raise UploadError("invalid_doc_id", "非法 document id。")
        return path

    def create(self, stream: BinaryIO, *, filename: str, content_type: str | None,
               identity, access_scope: str, groups: list[str]) -> dict:
        scope = (access_scope or "private").strip().lower()
        normalized_groups = list(dict.fromkeys(g.strip() for g in groups if g and g.strip()))
        acl = build_upload_acl(identity, scope, normalized_groups)
        safe_name = Path((filename or "").replace("\\", "/")).name
        suffix = Path(safe_name).suffix.lower()
        if not safe_name or suffix not in ALLOWED_SUFFIXES:
            raise UploadError("unsupported_type", "当前支持 .md、.markdown 和 .pdf 文档。")
        if len(safe_name) > MAX_FILENAME_CHARS:
            raise UploadError("filename_too_long", f"文件名不能超过 {MAX_FILENAME_CHARS} 个字符。")
        normalized_content_type = content_type or "application/octet-stream"
        if len(normalized_content_type) > MAX_CONTENT_TYPE_CHARS:
            raise UploadError(
                "content_type_too_long",
                f"Content-Type 不能超过 {MAX_CONTENT_TYPE_CHARS} 个字符。",
            )

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
            "content_type": normalized_content_type,
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
            "attempts": 0,
            "max_attempts": self.max_attempts,
            "created_at": now,
            "updated_at": now,
            "source_path": str(source),
        }
        try:
            persisted = self.repository.create(record)
        except Exception:
            # 文件已经完整落盘但业务事务没有建立时，不能留下永远无人认领的孤儿目录。
            shutil.rmtree(doc_dir, ignore_errors=True)
            raise
        return self.public_record(persisted)

    def _update(self, document_id: str, **changes) -> dict:
        return self.repository.update_by_document(document_id, **changes)

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

    def _claim_document(self, document_id: str, *, worker_id: str | None = None) -> dict | None:
        """本地兼容执行器按文档领取当前任务。"""
        return self.repository.claim_by_document(document_id, worker_id=worker_id)

    def _claim_job(self, job_id: str, *, worker_id: str | None = None) -> dict | None:
        """队列执行器按消息中的 job_id 领取，不能跨任务边界。"""
        return self.repository.claim_by_job(job_id, worker_id=worker_id)

    def process(self, document_id: str, *, worker_id: str | None = None,
                retry_on_transient: bool = False) -> dict | None:
        """按文档执行当前任务；仅供无 Redis 的 BackgroundTasks 兼容模式使用。"""
        record = self._claim_document(document_id, worker_id=worker_id)
        if record is None:
            current = self.repository.get_by_document(document_id)
            return self.public_record(current) if current else None
        return self._process_claimed(
            record, worker_id=worker_id, retry_on_transient=retry_on_transient)

    def process_job(self, job_id: str, *, worker_id: str | None = None,
                    retry_on_transient: bool = False) -> dict | None:
        """按 Celery 消息携带的 job_id 执行；领取前异常交给消息层重试。"""
        record = self._claim_job(job_id, worker_id=worker_id)
        if record is None:
            current = self.repository.get_job(job_id)
            return self.public_record(current) if current else None
        return self._process_claimed(
            record, worker_id=worker_id, retry_on_transient=retry_on_transient)

    def _process_claimed(self, record: dict, *, worker_id: str | None,
                         retry_on_transient: bool) -> dict | None:
        """处理一条已经成功领取的任务，并负责持久化业务重试或终态。"""
        document_id = record["document_id"]
        job_id = record["job_id"]
        try:
            stats = self._get_pipeline().run(
                record, lambda **changes: self._update(
                    document_id, expected_worker_id=worker_id, **changes))
            self._update(document_id, status="ready", stage="ready",
                         chunk_count=stats["chunk_count"],
                         parser_batch_id=stats.get("parser_batch_id"),
                         expected_worker_id=worker_id)
        except Exception as exc:
            code = exc.code if isinstance(exc, (UploadError, MinerUError)) else "index_failed"
            if code == "lease_lost":
                log.warning("upload lease lost: doc=%s worker=%s", document_id, worker_id)
                current = self.repository.get_job(job_id)
                return self.public_record(current) if current else None
            log.exception("upload processing failed: doc=%s code=%s", document_id, code)
            try:
                current = self.repository.get_job(job_id)
                if (retry_on_transient and current and
                        is_transient_ingestion_error(exc) and
                        hasattr(self.repository, "schedule_retry")):
                    delay = retry_delay_seconds(current.get("attempts", 1), current["job_id"])
                    self.repository.schedule_retry(
                        document_id, error_code=code, delay_seconds=delay,
                        expected_worker_id=worker_id)
                    log.warning(
                        "upload retry scheduled: doc=%s job=%s attempt=%s delay=%ss code=%s",
                        document_id, current["job_id"], current.get("attempts"), delay, code)
                else:
                    self._update(
                        document_id, status="failed", stage="failed", error_code=code,
                        expected_worker_id=worker_id)
            except Exception:
                log.exception("upload failure state could not be persisted: doc=%s", document_id)
        current = self.repository.get_job(job_id)
        return self.public_record(current) if current else None

    def get_job(self, job_id: str) -> dict | None:
        record = self.repository.get_job(job_id)
        return self.public_record(record) if record else None

    def retry_job(self, job_id: str) -> dict:
        """为失败文档创建一条新任务，保留数据库中的旧任务历史。"""
        new_job_id = f"job_{uuid.uuid4().hex}"
        record = self.repository.retry_failed(
            job_id, new_job_id=new_job_id, max_attempts=self.max_attempts)
        return self.public_record(record)

    def get_document(self, document_id: str) -> dict | None:
        record = self.repository.get_by_document(document_id)
        return self.public_record(record) if record else None

    def list_documents(self, *, tenant: str, owner: str | None = None,
                       include_deleted: bool = False, limit: int = 100,
                       offset: int = 0) -> list[dict]:
        records = self.repository.list_documents(
            tenant=tenant, owner=owner, include_deleted=include_deleted,
            limit=limit, offset=offset)
        return [self.public_record(record) for record in records]

    def reindex_document(self, document_id: str, *, access_scope: str | None = None,
                         groups: list[str] | None = None, acl: dict | None = None) -> dict:
        """从保留的原文件创建新摄取任务；旧任务历史由 SQL 仓储保留。"""
        new_job_id = f"job_{uuid.uuid4().hex}"
        record = self.repository.enqueue_reindex(
            document_id, new_job_id=new_job_id, max_attempts=self.max_attempts,
            access_scope=access_scope, groups=groups, acl=acl)
        return self.public_record(record)

    def update_access(self, document_id: str, *, identity,
                      access_scope: str, groups: list[str]) -> dict:
        """收紧或扩展 ACL，并重建向量 payload。

        旧索引必须先下线，避免数据库已显示新权限、Qdrant 却仍按旧权限提供结果。
        删除成功后才原子更新 ACL + 创建新任务；若建任务失败，文档至多暂时不可检索，
        不会继续以旧的、更宽权限暴露（fail closed）。
        """
        scope = (access_scope or "private").strip().lower()
        normalized_groups = list(dict.fromkeys(
            group.strip() for group in groups if group and group.strip()))
        current = self.repository.get_by_document(document_id)
        if current is None:
            raise UploadError("not_found", "文档不存在。")
        acl = build_upload_acl(
            identity, scope, normalized_groups, owner=current["owner"])
        job_id = f"job_{uuid.uuid4().hex}"
        self.repository.prepare_access_update(
            document_id, new_job_id=job_id, max_attempts=self.max_attempts)
        try:
            self._get_pipeline().delete_index(document_id)
            record = self.repository.activate_access_update(
                document_id, job_id=job_id, access_scope=scope,
                groups=normalized_groups, acl=acl)
        except Exception as exc:
            code = getattr(exc, "code", None) or "access_update_failed"
            try:
                self.repository.fail_access_update(
                    document_id, job_id=job_id, error_code=code)
            except Exception:
                log.exception(
                    "access update failure state could not be persisted: doc=%s",
                    document_id)
            raise
        return self.public_record(record)

    def delete_document(self, document_id: str) -> dict:
        """软删除管理记录，物理删除索引、sidecar 与本地原文。操作可安全重试。"""
        record = self.repository.begin_delete(document_id)
        if record.get("status") == "deleted":
            return self.public_record(record)
        try:
            self._get_pipeline().delete_index(document_id)
            doc_dir = self._doc_dir(document_id)
            if isinstance(self.repository, FileJobRepository):
                # JSON 兼容仓储把 record.json 放在文档目录内；保留它才能维持软删除审计。
                for child in doc_dir.iterdir() if doc_dir.exists() else ():
                    if child.name == "record.json":
                        continue
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
            elif doc_dir.exists():
                shutil.rmtree(doc_dir)
            record = self.repository.finish_delete(document_id)
        except Exception:
            try:
                self.repository.fail_delete(document_id)
            except Exception:
                log.exception("delete failure state could not be persisted: doc=%s", document_id)
            raise
        return self.public_record(record)

    @staticmethod
    def public_record(record: dict) -> dict:
        return {k: record.get(k) for k in (
            "document_id", "job_id", "tenant", "owner", "filename", "size", "sha256",
            "source_format", "access_scope", "groups", "status", "stage", "chunk_count",
            "parser_batch_id", "error_code",
            "job_status", "attempts", "max_attempts", "worker_id", "celery_task_id",
            "created_at", "updated_at", "started_at", "heartbeat_at", "finished_at")}
