"""文件兼容仓储与 PostgreSQL/SQLAlchemy 可靠任务仓储。"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
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
            record["updated_at"] = utcnow().isoformat()
            self._write(record)
            return record

    def claim_by_document(self, document_id: str, *, worker_id: str | None = None) -> dict | None:
        with self._lock:
            record = self._read(document_id)
            if record is None:
                raise UploadError("not_found", "文档任务不存在。")
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

    def claim_by_document(self, document_id: str, *, worker_id: str | None = None) -> dict | None:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            row = self._load(session, document_id=document_id, for_update=True)
            if not row:
                raise UploadError("not_found", "文档任务不存在。")
            job, document = row
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
            session.flush()
            return self._record(document, job)

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
        return {"recovered": recovered, "failed": failed}

    def mark_outbox_sent(self, job_id: str, celery_task_id: str) -> None:
        now = utcnow()
        with Session(self.engine) as session, session.begin():
            outbox = session.scalar(
                select(OutboxRow).where(OutboxRow.job_id == job_id).with_for_update())
            job = session.get(IngestionJobRow, job_id)
            if outbox is None or job is None:
                raise UploadError("not_found", "待投递任务不存在。")
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
            if outbox is None:
                return
            outbox.status = "pending"
            outbox.attempts += 1
            outbox.last_error = error_code[:160]
            # Outbox 自身也退避，但上限较短，Redis 恢复后能较快补投。
            delay = min(300, 5 * (2 ** min(outbox.attempts - 1, 6)))
            outbox.next_attempt_at = now + timedelta(seconds=delay)
            outbox.updated_at = now
