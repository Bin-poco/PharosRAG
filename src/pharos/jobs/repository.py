"""文件兼容仓储与 PostgreSQL/SQLAlchemy 可靠任务仓储。"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ..ingestion.errors import UploadError
from .models import Base, DocumentRow, IngestionJobRow, OutboxRow, utcnow


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return utcnow()


def _iso(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class FileJobRepository:
    """旧版原子 JSON 仓储；仅用于未配置数据库的本地兼容模式。"""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _doc_dir(self, document_id: str) -> Path:
        path = (self.root / document_id).resolve()
        if not path.is_relative_to(self.root):
            raise UploadError("invalid_doc_id", "非法 document id。")
        return path

    def _path(self, document_id: str) -> Path:
        return self._doc_dir(document_id) / "record.json"

    def _read(self, document_id: str) -> dict | None:
        path = self._path(document_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, record: dict) -> None:
        doc_dir = self._doc_dir(record["document_id"])
        doc_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(record["document_id"])
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)

    def create(self, record: dict) -> dict:
        with self._lock:
            self._write(record)
        return dict(record)

    def get_job(self, job_id: str) -> dict | None:
        for path in self.root.glob("upload__*/record.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if record.get("job_id") == job_id:
                return record
        return None

    def get_by_document(self, document_id: str) -> dict | None:
        with self._lock:
            return self._read(document_id)

    def list_documents(self, *, tenant: str, owner: str | None = None,
                       include_deleted: bool = False, limit: int = 100,
                       offset: int = 0) -> list[dict]:
        records = []
        with self._lock:
            for path in self.root.glob("upload__*/record.json"):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if record.get("tenant") != tenant:
                    continue
                if owner is not None and record.get("owner") != owner:
                    continue
                if not include_deleted and record.get("status") == "deleted":
                    continue
                records.append(record)
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        start = max(0, int(offset))
        return records[start:start + max(1, min(int(limit), 500))]

    def enqueue_reindex(self, document_id: str, *, new_job_id: str, max_attempts: int,
                        access_scope: str | None = None, groups: list[str] | None = None,
                        acl: dict | None = None) -> dict:
        with self._lock:
            record = self._read(document_id)
            if record is None:
                raise UploadError("not_found", "文档不存在。")
            if record.get("status") in {
                "queued", "running", "processing", "deleting", "updating_access"
            }:
                raise UploadError("document_busy", "文档正在处理中，请稍后重试。")
            if record.get("status") == "deleted":
                raise UploadError("document_deleted", "已删除文档不能重新建库。")
            now = utcnow().isoformat()
            record.update(
                job_id=new_job_id, status="queued", job_status="queued", stage="uploaded",
                attempts=0, max_attempts=max(1, int(max_attempts)), worker_id=None,
                celery_task_id=None, error_code=None, started_at=None, heartbeat_at=None,
                finished_at=None, updated_at=now,
            )
            if access_scope is not None:
                record.update(access_scope=access_scope, groups=list(groups or []), acl=dict(acl or {}))
            self._write(record)
            return record

    def prepare_access_update(self, document_id: str, *, new_job_id: str,
                              max_attempts: int) -> dict:
        """先占住文档但不投递任务，防止旧索引下线期间并发重建或删除。"""
        with self._lock:
            record = self._read(document_id)
            if record is None:
                raise UploadError("not_found", "文档不存在。")
            if record.get("status") in {
                "queued", "running", "processing", "deleting", "updating_access"
            }:
                raise UploadError("document_busy", "文档正在处理中，请稍后重试。")
            if record.get("status") == "deleted":
                raise UploadError("document_deleted", "已删除文档不能修改权限。")
            now = utcnow().isoformat()
            record.update(
                job_id=new_job_id, status="updating_access", job_status="held",
                stage="access_update_pending", attempts=0,
                max_attempts=max(1, int(max_attempts)), worker_id=None,
                celery_task_id=None, error_code=None, started_at=None,
                heartbeat_at=None, finished_at=None, updated_at=now,
            )
            self._write(record)
            return record

    def activate_access_update(self, document_id: str, *, job_id: str,
                               access_scope: str, groups: list[str], acl: dict) -> dict:
        with self._lock:
            record = self._read(document_id)
            if (record is None or record.get("job_id") != job_id or
                    record.get("job_status") != "held"):
                raise UploadError("lifecycle_conflict", "权限修改任务已失去执行权。")
            record.update(
                access_scope=access_scope, groups=list(groups), acl=dict(acl),
                status="queued", job_status="queued", stage="uploaded",
                chunk_count=0, parser_batch_id=None, updated_at=utcnow().isoformat(),
            )
            self._write(record)
            return record

    def fail_access_update(self, document_id: str, *, job_id: str,
                           error_code: str) -> None:
        with self._lock:
            record = self._read(document_id)
            if (record is None or record.get("job_id") != job_id or
                    record.get("job_status") != "held"):
                return
            now = utcnow().isoformat()
            record.update(
                status="access_update_failed", job_status="failed",
                stage="access_update_failed", error_code=error_code,
                finished_at=now, updated_at=now,
            )
            self._write(record)

    def begin_delete(self, document_id: str) -> dict:
        with self._lock:
            record = self._read(document_id)
            if record is None:
                raise UploadError("not_found", "文档不存在。")
            if record.get("status") == "deleted":
                return record
            if record.get("status") in {
                "queued", "running", "processing", "updating_access"
            }:
                raise UploadError("document_busy", "文档正在处理中，不能删除。")
            record["status"] = "deleting"
            record["updated_at"] = utcnow().isoformat()
            self._write(record)
            return record

    def finish_delete(self, document_id: str) -> dict:
        return self.update_by_document(document_id, status="deleted", chunk_count=0)

    def fail_delete(self, document_id: str) -> None:
        try:
            self.update_by_document(document_id, status="delete_failed")
        except UploadError:
            pass

    def update_by_document(self, document_id: str, *, expected_worker_id: str | None = None,
                           **changes) -> dict:
        with self._lock:
            record = self._read(document_id)
            if record is None:
                raise UploadError("not_found", "文档任务不存在。")
            if (expected_worker_id is not None and
                    (record.get("status") != "running" or
                     record.get("worker_id") != expected_worker_id)):
                raise UploadError("lease_lost", "任务执行权已转交给其他 Worker。")
            record.update(changes)
            if changes.get("status") == "ready":
                record["job_status"] = "succeeded"
                record["finished_at"] = utcnow().isoformat()
            elif changes.get("status") == "failed":
                record["job_status"] = "failed"
                record["finished_at"] = utcnow().isoformat()
            elif changes.get("status") == "running":
                record["job_status"] = "running"
            record["updated_at"] = utcnow().isoformat()
            self._write(record)
            return record

    def claim_by_document(self, document_id: str, *, worker_id: str | None = None) -> dict | None:
        with self._lock:
            record = self._read(document_id)
            if record is None:
                raise UploadError("not_found", "文档任务不存在。")
            return self._claim_record(record, worker_id=worker_id)

    def claim_by_job(self, job_id: str, *, worker_id: str | None = None) -> dict | None:
        """按消息携带的 job_id 领取，旧消息不能越过 job 边界执行新任务。"""
        with self._lock:
            record = self.get_job(job_id)
            if record is None:
                return None
            return self._claim_record(record, worker_id=worker_id)

    def _claim_record(self, record: dict, *, worker_id: str | None = None) -> dict | None:
        """File 仓储的单记录领取实现；调用方必须持有 ``self._lock``。"""
        if record.get("job_id") is None:
            return None
        if record.get("status") != "queued":
            return None
        record.update(
            status="running",
            job_status="running",
            stage="parsing",
            attempts=int(record.get("attempts", 0)) + 1,
            worker_id=worker_id,
            error_code=None,
            updated_at=utcnow().isoformat(),
        )
        self._write(record)
        return record

    def heartbeat(self, job_id: str, worker_id: str) -> bool:
        with self._lock:
            record = self.get_job(job_id)
            if not record or record.get("status") != "running":
                return False
            if record.get("worker_id") not in {None, worker_id}:
                return False
            record["heartbeat_at"] = utcnow().isoformat()
            self._write(record)
            return True

    def retry_failed(self, job_id: str, *, new_job_id: str, max_attempts: int) -> dict:
        with self._lock:
            record = self.get_job(job_id)
            if record is None:
                raise UploadError("not_found", "文档任务不存在。")
            if record.get("job_status", record.get("status")) != "failed":
                raise UploadError("job_not_retryable", "只有失败任务可以手动重试。")
            if record.get("stage") == "access_update_failed":
                raise UploadError(
                    "job_not_retryable", "权限修改失败需重新提交 PATCH access，不能盲目重放旧 ACL。")
            now = utcnow().isoformat()
            record.update(
                job_id=new_job_id, status="queued", job_status="queued", stage="uploaded",
                attempts=0, max_attempts=max(1, int(max_attempts)), worker_id=None,
                celery_task_id=None, error_code=None, started_at=None, heartbeat_at=None,
                finished_at=None, updated_at=now,
            )
            self._write(record)
            return record


class SQLJobRepository:
    """关系数据库是文档与任务状态的唯一真相来源。"""

    def __init__(self, database_url: str, *, create_schema: bool = False):
        kwargs = {"pool_pre_ping": True}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.engine = create_engine(database_url, **kwargs)
        if create_schema:
            Base.metadata.create_all(self.engine)

    @staticmethod
    def _record(document: DocumentRow, job: IngestionJobRow) -> dict:
        return {
            "document_id": document.document_id,
            "job_id": job.job_id,
            "tenant": document.tenant,
            "owner": document.owner,
            "filename": document.filename,
            "content_type": document.content_type,
            "source_format": document.source_format,
            "size": document.size,
            "sha256": document.sha256,
            "access_scope": document.access_scope,
            "groups": list(document.groups or []),
            "acl": dict(document.acl or {}),
            "source_path": document.source_path,
            "status": document.status,
            "job_status": job.status,
            "stage": job.stage,
            "chunk_count": document.chunk_count,
            "parser_batch_id": document.parser_batch_id,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "worker_id": job.worker_id,
            "celery_task_id": job.celery_task_id,
            "error_code": job.error_code,
            "created_at": _iso(document.created_at),
            "updated_at": _iso(max(_aware(document.updated_at), _aware(job.updated_at))),
            "started_at": _iso(job.started_at),
            "heartbeat_at": _iso(job.heartbeat_at),
            "finished_at": _iso(job.finished_at),
        }

    def create(self, record: dict) -> dict:
        now = _as_datetime(record.get("created_at"))
        with Session(self.engine) as session, session.begin():
            document = DocumentRow(
                document_id=record["document_id"], tenant=record["tenant"],
                owner=record["owner"], filename=record["filename"],
                content_type=record["content_type"], source_format=record["source_format"],
                size=record["size"], sha256=record["sha256"],
                access_scope=record["access_scope"], groups=record["groups"],
                acl=record["acl"], source_path=record["source_path"], status="queued",
                chunk_count=0, current_job_id=record["job_id"],
                created_at=now, updated_at=now,
            )
            job = IngestionJobRow(
                job_id=record["job_id"], document_id=record["document_id"],
                status="queued", stage="uploaded", attempts=0,
                max_attempts=int(record.get("max_attempts", 3)), available_at=now,
                created_at=now, updated_at=now,
            )
            session.add(document)
            session.flush()
            session.add(job)
            session.flush()
            session.add(OutboxRow(
                job_id=job.job_id, event_type="ingestion.requested",
                payload={"job_id": job.job_id}, status="pending", attempts=0,
                next_attempt_at=now, created_at=now, updated_at=now,
            ))
            session.flush()
            return self._record(document, job)

    def _load(self, session: Session, *, job_id: str | None = None,
              document_id: str | None = None, for_update: bool = False):
        statement = select(IngestionJobRow, DocumentRow).join(
            DocumentRow, DocumentRow.document_id == IngestionJobRow.document_id)
        if job_id is not None:
            statement = statement.where(IngestionJobRow.job_id == job_id)
        else:
            statement = statement.where(
                IngestionJobRow.document_id == document_id,
                DocumentRow.current_job_id == IngestionJobRow.job_id,
            )
        if for_update:
            statement = statement.with_for_update()
        return session.execute(statement).first()

    def get_job(self, job_id: str) -> dict | None:
        with Session(self.engine) as session:
            row = self._load(session, job_id=job_id)
            return self._record(row[1], row[0]) if row else None

    def get_by_document(self, document_id: str) -> dict | None:
        with Session(self.engine) as session:
            row = self._load(session, document_id=document_id)
            return self._record(row[1], row[0]) if row else None

    def list_documents(self, *, tenant: str, owner: str | None = None,
                       include_deleted: bool = False, limit: int = 100,
                       offset: int = 0) -> list[dict]:
        with Session(self.engine) as session:
            statement = (select(IngestionJobRow, DocumentRow)
                         .join(DocumentRow, DocumentRow.document_id == IngestionJobRow.document_id)
                         .where(DocumentRow.current_job_id == IngestionJobRow.job_id,
                                DocumentRow.tenant == tenant))
            if owner is not None:
                statement = statement.where(DocumentRow.owner == owner)
            if not include_deleted:
                statement = statement.where(DocumentRow.status != "deleted")
            statement = (statement.order_by(DocumentRow.created_at.desc())
                         .offset(max(0, int(offset)))
                         .limit(max(1, min(int(limit), 500))))
            return [self._record(document, job)
                    for job, document in session.execute(statement)]

    @staticmethod
    def _enqueue_job(session: Session, document: DocumentRow, *, new_job_id: str,
                     max_attempts: int, now: datetime) -> IngestionJobRow:
        job = IngestionJobRow(
            job_id=new_job_id, document_id=document.document_id,
            status="queued", stage="uploaded", attempts=0,
            max_attempts=max(1, int(max_attempts)), available_at=now,
            created_at=now, updated_at=now,
        )
        session.add(job)
        session.flush()
        document.current_job_id = new_job_id
        document.status = "queued"
        document.updated_at = now
        session.add(OutboxRow(
            job_id=new_job_id, event_type="ingestion.requested",
            payload={"job_id": new_job_id}, status="pending", attempts=0,
            next_attempt_at=now, created_at=now, updated_at=now,
        ))
        session.flush()
        return job

    def enqueue_reindex(self, document_id: str, *, new_job_id: str, max_attempts: int,
                        access_scope: str | None = None, groups: list[str] | None = None,
                        acl: dict | None = None) -> dict:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            row = self._load(session, document_id=document_id, for_update=True)
            if not row:
                raise UploadError("not_found", "文档不存在。")
            current_job, document = row
            if current_job.status in {"held", "queued", "retrying", "running"}:
                raise UploadError("document_busy", "文档正在处理中，请稍后重试。")
            if document.status in {"deleting", "delete_failed"}:
                raise UploadError("document_busy", "文档正在删除，不能重新建库。")
            if document.status == "deleted":
                raise UploadError("document_deleted", "已删除文档不能重新建库。")
            if access_scope is not None:
                document.access_scope = access_scope
                document.groups = list(groups or [])
                document.acl = dict(acl or {})
            job = self._enqueue_job(
                session, document, new_job_id=new_job_id,
                max_attempts=max_attempts, now=now)
            return self._record(document, job)

    def prepare_access_update(self, document_id: str, *, new_job_id: str,
                              max_attempts: int) -> dict:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            row = self._load(session, document_id=document_id, for_update=True)
            if not row:
                raise UploadError("not_found", "文档不存在。")
            current_job, document = row
            if current_job.status in {"held", "queued", "retrying", "running"}:
                raise UploadError("document_busy", "文档正在处理中，请稍后重试。")
            if document.status in {"deleting", "delete_failed"}:
                raise UploadError("document_busy", "文档正在删除，不能修改权限。")
            if document.status == "deleted":
                raise UploadError("document_deleted", "已删除文档不能修改权限。")
            job = IngestionJobRow(
                job_id=new_job_id, document_id=document.document_id,
                status="held", stage="access_update_pending", attempts=0,
                max_attempts=max(1, int(max_attempts)), available_at=now,
                created_at=now, updated_at=now,
            )
            session.add(job)
            session.flush()
            document.current_job_id = new_job_id
            document.status = "updating_access"
            document.updated_at = now
            session.flush()
            return self._record(document, job)

    def activate_access_update(self, document_id: str, *, job_id: str,
                               access_scope: str, groups: list[str], acl: dict) -> dict:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            row = self._load(session, document_id=document_id, for_update=True)
            if not row:
                raise UploadError("not_found", "文档不存在。")
            job, document = row
            if job.job_id != job_id or job.status != "held":
                raise UploadError("lifecycle_conflict", "权限修改任务已失去执行权。")
            document.access_scope = access_scope
            document.groups = list(groups)
            document.acl = dict(acl)
            document.status = "queued"
            document.chunk_count = 0
            document.parser_batch_id = None
            document.updated_at = now
            job.status = "queued"
            job.stage = "uploaded"
            job.updated_at = now
            session.add(OutboxRow(
                job_id=job_id, event_type="ingestion.requested",
                payload={"job_id": job_id}, status="pending", attempts=0,
                next_attempt_at=now, created_at=now, updated_at=now,
            ))
            session.flush()
            return self._record(document, job)

    def fail_access_update(self, document_id: str, *, job_id: str,
                           error_code: str) -> None:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            row = self._load(session, document_id=document_id, for_update=True)
            if not row:
                return
            job, document = row
            if job.job_id != job_id or job.status != "held":
                return
            document.status = "access_update_failed"
            document.updated_at = now
            job.status = "failed"
            job.stage = "access_update_failed"
            job.error_code = error_code
            job.finished_at = now
            job.updated_at = now

    def begin_delete(self, document_id: str) -> dict:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            row = self._load(session, document_id=document_id, for_update=True)
            if not row:
                raise UploadError("not_found", "文档不存在。")
            job, document = row
            if document.status == "deleted":
                return self._record(document, job)
            if job.status in {"held", "queued", "retrying", "running"}:
                raise UploadError("document_busy", "文档正在处理中，不能删除。")
            document.status = "deleting"
            document.updated_at = now
            return self._record(document, job)

    def finish_delete(self, document_id: str) -> dict:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            row = self._load(session, document_id=document_id, for_update=True)
            if not row:
                raise UploadError("not_found", "文档不存在。")
            job, document = row
            document.status = "deleted"
            document.chunk_count = 0
            document.updated_at = now
            return self._record(document, job)

    def fail_delete(self, document_id: str) -> None:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            row = self._load(session, document_id=document_id, for_update=True)
            if not row:
                return
            job, document = row
            if document.status == "deleting":
                document.status = "delete_failed"
                document.updated_at = now

    def _claim_row(self, session: Session, row, *, worker_id: str | None = None,
                   require_current: bool = True) -> dict | None:
        now = utcnow()
        job, document = row
        if require_current and document.current_job_id != job.job_id:
            return None
        if job.status not in {"queued", "retrying"} or _aware(job.available_at) > now:
            return None
        job.status = "running"
        job.stage = "parsing"
        job.attempts += 1
        job.worker_id = worker_id
        job.error_code = None
        job.error_message = None
        job.started_at = job.started_at or now
        job.heartbeat_at = now
        job.updated_at = now
        document.status = "processing"
        document.updated_at = now
        outbox = session.scalar(
            select(OutboxRow).where(OutboxRow.job_id == job.job_id).with_for_update())
        if outbox is not None:
            # consumed 与任务领取在同一事务提交，表示消息已经真正进入业务处理。
            outbox.status = "consumed"
            outbox.updated_at = now
        session.flush()
        return self._record(document, job)

    def claim_by_document(self, document_id: str, *, worker_id: str | None = None) -> dict | None:
        """兼容本地 BackgroundTasks；队列 Worker 必须使用 ``claim_by_job``。"""
        with Session(self.engine) as session, session.begin():
            row = self._load(session, document_id=document_id, for_update=True)
            if not row:
                raise UploadError("not_found", "文档任务不存在。")
            return self._claim_row(session, row, worker_id=worker_id)

    def claim_by_job(self, job_id: str, *, worker_id: str | None = None) -> dict | None:
        """原子领取指定 job；迟到的旧消息绝不能领取文档的新 current job。"""
        with Session(self.engine) as session, session.begin():
            row = self._load(session, job_id=job_id, for_update=True)
            if not row:
                return None
            return self._claim_row(session, row, worker_id=worker_id)

    def update_by_document(self, document_id: str, *, expected_worker_id: str | None = None,
                           **changes) -> dict:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            row = self._load(session, document_id=document_id, for_update=True)
            if not row:
                raise UploadError("not_found", "文档任务不存在。")
            job, document = row
            if (expected_worker_id is not None and
                    (job.status != "running" or job.worker_id != expected_worker_id)):
                raise UploadError("lease_lost", "任务执行权已转交给其他 Worker。")
            if "stage" in changes:
                job.stage = changes["stage"]
            if "parser_batch_id" in changes:
                document.parser_batch_id = changes["parser_batch_id"]
            if "chunk_count" in changes:
                document.chunk_count = int(changes["chunk_count"])
            if "error_code" in changes:
                job.error_code = changes["error_code"]
            status = changes.get("status")
            if status == "ready":
                document.status = "ready"
                job.status = "succeeded"
                job.finished_at = now
            elif status == "failed":
                document.status = "failed"
                job.status = "failed"
                job.finished_at = now
            elif status == "running":
                document.status = "processing"
                job.status = "running"
            job.heartbeat_at = now
            job.updated_at = now
            document.updated_at = now
            session.flush()
            return self._record(document, job)

    def list_pending_outbox(self, limit: int = 100) -> list[str]:
        now = utcnow()
        with Session(self.engine) as session:
            statement = (select(OutboxRow.job_id)
                         .join(IngestionJobRow, IngestionJobRow.job_id == OutboxRow.job_id)
                         .where(OutboxRow.status == "pending",
                                OutboxRow.next_attempt_at <= now,
                                IngestionJobRow.available_at <= now,
                                IngestionJobRow.status.in_({"queued", "retrying"}))
                         .order_by(OutboxRow.id)
                         .limit(max(1, min(int(limit), 1000))))
            return list(session.scalars(statement))

    def begin_outbox_publish(self, job_id: str) -> bool:
        """原子预占一条待投递消息，避免多个 dispatcher 重复发布。"""
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            outbox = session.scalar(
                select(OutboxRow).where(OutboxRow.job_id == job_id).with_for_update())
            job = session.get(IngestionJobRow, job_id)
            if (outbox is None or job is None or outbox.status != "pending" or
                    _aware(outbox.next_attempt_at) > now or
                    job.status not in {"queued", "retrying"} or
                    _aware(job.available_at) > now):
                return False
            outbox.status = "publishing"
            outbox.updated_at = now
            return True

    def heartbeat(self, job_id: str, worker_id: str) -> bool:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            job = session.scalar(
                select(IngestionJobRow).where(
                    IngestionJobRow.job_id == job_id,
                    IngestionJobRow.status == "running",
                    IngestionJobRow.worker_id == worker_id,
                ).with_for_update())
            if job is None:
                return False
            job.heartbeat_at = now
            job.updated_at = now
            return True

    def schedule_retry(self, document_id: str, *, error_code: str, delay_seconds: int,
                       expected_worker_id: str | None = None) -> dict:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            row = self._load(session, document_id=document_id, for_update=True)
            if not row:
                raise UploadError("not_found", "文档任务不存在。")
            job, document = row
            if (expected_worker_id is not None and
                    (job.status != "running" or job.worker_id != expected_worker_id)):
                raise UploadError("lease_lost", "任务执行权已转交给其他 Worker。")
            if job.attempts >= job.max_attempts:
                job.status = "failed"
                job.stage = "failed"
                job.error_code = error_code
                job.error_message = None
                job.finished_at = now
                document.status = "failed"
            else:
                available = now + timedelta(seconds=max(1, int(delay_seconds)))
                job.status = "retrying"
                job.stage = "waiting_retry"
                job.error_code = error_code
                job.error_message = None
                job.available_at = available
                job.worker_id = None
                document.status = "queued"
                outbox = session.scalar(
                    select(OutboxRow).where(OutboxRow.job_id == job.job_id).with_for_update())
                if outbox is not None:
                    outbox.status = "pending"
                    outbox.next_attempt_at = available
                    outbox.sent_at = None
                    outbox.last_error = None
                    outbox.updated_at = now
            job.heartbeat_at = now
            job.updated_at = now
            document.updated_at = now
            session.flush()
            return self._record(document, job)

    def recover_unclaimed(self, stale_seconds: int, limit: int = 100,
                          publishing_stale_seconds: int = 60) -> dict:
        """重新开放发布中断或已发布但长期未被 Worker 领取的消息。

        Redis 中仍然排队的原消息可能稍后到达，因此这里只恢复成 pending；真正执行仍由
        ``claim_by_job`` 的数据库行锁和 current-job 校验保证幂等。
        """
        now = utcnow()
        sent_cutoff = now - timedelta(seconds=max(1, int(stale_seconds)))
        publishing_cutoff = now - timedelta(seconds=max(1, int(publishing_stale_seconds)))
        recovered = 0
        with Session(self.engine) as session, session.begin():
            # 先只找候选 id，再逐条按 job -> outbox 的全局固定顺序加锁。
            # 直接对 outbox join job 做 FOR UPDATE 时，数据库执行计划可能先锁 outbox，
            # 与 Worker 的 job -> outbox 顺序相反，仍可能形成死锁。
            job_ids = list(session.scalars(
                select(OutboxRow.job_id)
                .join(IngestionJobRow, IngestionJobRow.job_id == OutboxRow.job_id)
                .where(
                    or_(
                        (OutboxRow.status == "sent") &
                        OutboxRow.sent_at.is_not(None) &
                        (OutboxRow.sent_at < sent_cutoff),
                        (OutboxRow.status == "publishing") &
                        (OutboxRow.updated_at < publishing_cutoff),
                    ),
                    IngestionJobRow.status.in_({"queued", "retrying"}),
                    IngestionJobRow.available_at <= now,
                )
                .order_by(OutboxRow.updated_at)
                .limit(max(1, min(int(limit), 1000)))))
            for job_id in job_ids:
                job = session.scalar(
                    select(IngestionJobRow)
                    .where(IngestionJobRow.job_id == job_id)
                    .with_for_update(skip_locked=True))
                if job is None:
                    continue
                outbox = session.scalar(
                    select(OutboxRow)
                    .where(OutboxRow.job_id == job_id)
                    .with_for_update(skip_locked=True))
                if outbox is None:
                    continue
                # 候选查询与取得行锁之间状态可能已经变化，锁内必须重新校验。
                stale_sent = (outbox.status == "sent" and outbox.sent_at is not None and
                              _aware(outbox.sent_at) < sent_cutoff)
                stale_publishing = (outbox.status == "publishing" and
                                    _aware(outbox.updated_at) < publishing_cutoff)
                if (not (stale_sent or stale_publishing) or
                        job.status not in {"queued", "retrying"} or
                        _aware(job.available_at) > now):
                    continue
                outbox.status = "pending"
                outbox.next_attempt_at = now
                outbox.sent_at = None
                outbox.last_error = "delivery_unconfirmed"
                outbox.updated_at = now
                job.celery_task_id = None
                job.updated_at = now
                recovered += 1
        return {"unclaimed_recovered": recovered}

    def recover_stale(self, stale_seconds: int, limit: int = 100) -> dict:
        now = utcnow()
        cutoff = now - timedelta(seconds=max(1, int(stale_seconds)))
        recovered = failed = 0
        with Session(self.engine) as session, session.begin():
            jobs = list(session.scalars(
                select(IngestionJobRow)
                .where(IngestionJobRow.status == "running",
                       IngestionJobRow.heartbeat_at < cutoff)
                .order_by(IngestionJobRow.heartbeat_at)
                .limit(max(1, min(int(limit), 1000)))
                .with_for_update(skip_locked=True)))
            for job in jobs:
                document = session.get(DocumentRow, job.document_id)
                if document is None:
                    continue
                if job.attempts >= job.max_attempts:
                    job.status = "failed"
                    job.stage = "failed"
                    job.error_code = "worker_lost"
                    job.finished_at = now
                    document.status = "failed"
                    failed += 1
                else:
                    job.status = "retrying"
                    job.stage = "waiting_retry"
                    job.error_code = "worker_lost"
                    job.available_at = now
                    job.worker_id = None
                    document.status = "queued"
                    outbox = session.scalar(
                        select(OutboxRow).where(OutboxRow.job_id == job.job_id).with_for_update())
                    if outbox is not None:
                        outbox.status = "pending"
                        outbox.next_attempt_at = now
                        outbox.sent_at = None
                        outbox.updated_at = now
                    recovered += 1
                job.updated_at = now
                document.updated_at = now

            # 权限修改在同步 HTTP 请求内完成；若进程恰好在“占位”后退出，held 不会被
            # Worker 领取。超时后明确标成可见失败，用户即可安全重试，而不是永久 busy。
            held_jobs = list(session.scalars(
                select(IngestionJobRow)
                .where(IngestionJobRow.status == "held",
                       IngestionJobRow.updated_at < cutoff)
                .order_by(IngestionJobRow.updated_at)
                .limit(max(1, min(int(limit), 1000)))
                .with_for_update(skip_locked=True)))
            for job in held_jobs:
                document = session.get(DocumentRow, job.document_id)
                if document is None or document.current_job_id != job.job_id:
                    continue
                job.status = "failed"
                job.stage = "access_update_failed"
                job.error_code = "access_update_interrupted"
                job.finished_at = now
                job.updated_at = now
                document.status = "access_update_failed"
                document.updated_at = now
                failed += 1

            # 删除同样是同步清理；进程中断后保留 delete_failed，下一次 DELETE 会从
            # 幂等的 Qdrant/sidecar/本地文件清理继续执行。
            deleting_documents = list(session.scalars(
                select(DocumentRow)
                .where(DocumentRow.status == "deleting",
                       DocumentRow.updated_at < cutoff)
                .order_by(DocumentRow.updated_at)
                .limit(max(1, min(int(limit), 1000)))
                .with_for_update(skip_locked=True)))
            for document in deleting_documents:
                document.status = "delete_failed"
                document.updated_at = now
                failed += 1
        return {"recovered": recovered, "failed": failed}

    def retry_failed(self, job_id: str, *, new_job_id: str, max_attempts: int) -> dict:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            row = self._load(session, job_id=job_id, for_update=True)
            if not row:
                raise UploadError("not_found", "文档任务不存在。")
            old_job, document = row
            if document.current_job_id != old_job.job_id or old_job.status != "failed":
                raise UploadError("job_not_retryable", "只有当前失败任务可以手动重试。")
            if old_job.stage == "access_update_failed":
                raise UploadError(
                    "job_not_retryable", "权限修改失败需重新提交 PATCH access，不能盲目重放旧 ACL。")
            job = IngestionJobRow(
                job_id=new_job_id, document_id=document.document_id,
                status="queued", stage="uploaded", attempts=0,
                max_attempts=max(1, int(max_attempts)), available_at=now,
                created_at=now, updated_at=now,
            )
            session.add(job)
            session.flush()
            document.current_job_id = new_job_id
            document.status = "queued"
            document.chunk_count = 0
            document.parser_batch_id = None
            document.updated_at = now
            session.add(OutboxRow(
                job_id=new_job_id, event_type="ingestion.requested",
                payload={"job_id": new_job_id}, status="pending", attempts=0,
                next_attempt_at=now, created_at=now, updated_at=now,
            ))
            session.flush()
            return self._record(document, job)

    def mark_outbox_sent(self, job_id: str, celery_task_id: str) -> None:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            # 与 Worker 领取任务的 _claim_row 保持同一锁序：job -> outbox。
            # 若这里反过来先锁 outbox，极速 Worker 会形成
            # API(outbox 等 job) <-> Worker(job 等 outbox) 的 PostgreSQL 死锁。
            job = session.get(IngestionJobRow, job_id, with_for_update=True)
            outbox = session.scalar(
                select(OutboxRow).where(OutboxRow.job_id == job_id).with_for_update())
            if outbox is None or job is None:
                raise UploadError("not_found", "待投递任务不存在。")
            # 只提交自己预占的 publishing 状态。Worker 可能已经把它推进到 consumed，
            # 甚至领取后失败并改回 pending 等待重试；任何一种都不能被迟到回写覆盖。
            if outbox.status == "publishing":
                outbox.status = "sent"
                outbox.sent_at = now
                outbox.last_error = None
                outbox.attempts += 1
                outbox.updated_at = now
            job.celery_task_id = celery_task_id
            job.updated_at = now

    def mark_outbox_failed(self, job_id: str, error_code: str = "broker_unavailable") -> None:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            outbox = session.scalar(
                select(OutboxRow).where(OutboxRow.job_id == job_id).with_for_update())
            if outbox is None or outbox.status != "publishing":
                return
            outbox.status = "pending"
            outbox.attempts += 1
            outbox.last_error = error_code[:160]
            # Outbox 自身也退避，但上限较短，Redis 恢复后能较快补投。
            delay = min(300, 5 * (2 ** min(outbox.attempts - 1, 6)))
            outbox.next_attempt_at = now + timedelta(seconds=delay)
            outbox.updated_at = now
