"""文档/任务关系数据库仓储测试。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pharos.ingestion import UploadError
from pharos.jobs.models import IngestionJobRow, OutboxRow, utcnow
from pharos.jobs.dispatcher import CeleryJobDispatcher
from pharos.jobs.repository import SQLJobRepository


def _record() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "document_id": "upload__db1",
        "job_id": "job_db1",
        "tenant": "t1",
        "owner": "alice",
        "filename": "guide.md",
        "content_type": "text/markdown",
        "source_format": "markdown",
        "size": 7,
        "sha256": "a" * 64,
        "access_scope": "private",
        "groups": [],
        "acl": {"tenant": "t1", "allow": ["user:alice"],
                "visibility": "restricted", "unset": False},
        "source_path": "/data/uploads/upload__db1/source.md",
        "status": "queued",
        "stage": "uploaded",
        "chunk_count": 0,
        "attempts": 0,
        "max_attempts": 3,
        "created_at": now,
        "updated_at": now,
    }


def test_sql_repository_persists_document_job_and_outbox(tmp_path):
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    repository = SQLJobRepository(url, create_schema=True)
    created = repository.create(_record())

    assert created["status"] == "queued"
    assert created["job_status"] == "queued"
    assert created["attempts"] == 0
    with Session(repository.engine) as session:
        assert session.scalar(select(func.count()).select_from(OutboxRow)) == 1

    # 新仓储实例仍能直接按主键读取，不依赖进程内状态或目录扫描。
    reopened = SQLJobRepository(url)
    assert reopened.get_job("job_db1")["owner"] == "alice"


def test_sql_repository_claim_is_single_owner_and_tracks_terminal_state(tmp_path):
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    first = SQLJobRepository(url, create_schema=True)
    second = SQLJobRepository(url)
    first.create(_record())

    claimed = first.claim_by_job("job_db1", worker_id="worker-a")
    assert claimed["status"] == "processing"
    assert claimed["job_status"] == "running"
    assert claimed["attempts"] == 1
    assert claimed["worker_id"] == "worker-a"
    assert second.claim_by_job("job_db1", worker_id="worker-b") is None
    with Session(first.engine) as session:
        assert session.scalar(select(OutboxRow.status)) == "consumed"

    first.update_by_document("upload__db1", stage="embedding")
    ready = first.update_by_document(
        "upload__db1", status="ready", stage="ready", chunk_count=4)
    assert ready["status"] == "ready"
    assert ready["job_status"] == "succeeded"
    assert ready["chunk_count"] == 4
    assert ready["finished_at"] is not None


def test_dispatcher_publishes_only_job_id_and_marks_outbox_sent(tmp_path):
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(_record())

    class FakeCelery:
        calls = []

        def send_task(self, name, *, args, task_id):
            self.calls.append((name, args, task_id))

    celery = FakeCelery()
    task_id = CeleryJobDispatcher(repository, celery).dispatch("job_db1")
    record = repository.get_job("job_db1")

    assert celery.calls == [("pharos.ingest_document", ["job_db1"], task_id)]
    assert record["celery_task_id"] == task_id
    assert repository.list_pending_outbox() == []


def test_dispatcher_publish_failure_releases_reservation_with_backoff(tmp_path):
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(_record())

    class UnavailableCelery:
        def send_task(self, name, *, args, task_id):
            raise ConnectionError("broker unavailable")

    with pytest.raises(ConnectionError):
        CeleryJobDispatcher(repository, UnavailableCelery()).dispatch("job_db1")

    with Session(repository.engine) as session:
        outbox = session.scalar(select(OutboxRow).where(OutboxRow.job_id == "job_db1"))
        assert outbox.status == "pending"
        assert outbox.attempts == 1
        assert outbox.last_error == "broker_unavailable"
    assert repository.list_pending_outbox() == []


def test_retry_waits_until_available_and_next_worker_can_claim(tmp_path):
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(_record())
    repository.claim_by_job("job_db1", worker_id="worker-a")

    assert repository.heartbeat("job_db1", "worker-b") is False
    assert repository.heartbeat("job_db1", "worker-a") is True
    retrying = repository.schedule_retry(
        "upload__db1", error_code="mineru_timeout", delay_seconds=60,
        expected_worker_id="worker-a")

    assert retrying["job_status"] == "retrying"
    assert retrying["stage"] == "waiting_retry"
    assert retrying["attempts"] == 1
    assert repository.list_pending_outbox() == []
    assert repository.claim_by_job("job_db1", worker_id="worker-b") is None

    # 模拟退避时间已经过去，任务重新进入 Outbox 并可被另一个 Worker 领取。
    available = utcnow() - timedelta(seconds=1)
    with Session(repository.engine) as session, session.begin():
        session.get(IngestionJobRow, "job_db1").available_at = available
        session.scalar(select(OutboxRow).where(OutboxRow.job_id == "job_db1")).next_attempt_at = available
    assert repository.list_pending_outbox() == ["job_db1"]
    claimed = repository.claim_by_job("job_db1", worker_id="worker-b")
    assert claimed["attempts"] == 2 and claimed["worker_id"] == "worker-b"


def test_worker_lease_prevents_stale_worker_from_overwriting_state(tmp_path):
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(_record())
    repository.claim_by_job("job_db1", worker_id="worker-a")

    with pytest.raises(UploadError) as exc:
        repository.update_by_document(
            "upload__db1", expected_worker_id="worker-b", stage="embedding")
    assert exc.value.code == "lease_lost"
    assert repository.get_job("job_db1")["stage"] == "parsing"


def test_stale_running_job_is_recovered_through_outbox(tmp_path):
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(_record())
    assert repository.begin_outbox_publish("job_db1") is True
    repository.mark_outbox_sent("job_db1", "celery-1")
    repository.claim_by_job("job_db1", worker_id="dead-worker")
    with Session(repository.engine) as session, session.begin():
        session.get(IngestionJobRow, "job_db1").heartbeat_at = utcnow() - timedelta(minutes=10)

    result = repository.recover_stale(stale_seconds=120)
    record = repository.get_job("job_db1")

    assert result == {"recovered": 1, "failed": 0}
    assert record["job_status"] == "retrying"
    assert record["error_code"] == "worker_lost"
    assert repository.list_pending_outbox() == ["job_db1"]


def test_retry_budget_exhaustion_is_terminal(tmp_path):
    record = _record()
    record["max_attempts"] = 1
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(record)
    repository.claim_by_job("job_db1", worker_id="worker-a")

    failed = repository.schedule_retry(
        "upload__db1", error_code="mineru_timeout", delay_seconds=10,
        expected_worker_id="worker-a")
    assert failed["job_status"] == "failed"
    assert failed["status"] == "failed"
    assert repository.list_pending_outbox() == []


def test_manual_retry_creates_new_job_and_preserves_failed_history(tmp_path):
    record = _record()
    record["max_attempts"] = 1
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(record)
    repository.claim_by_job("job_db1", worker_id="worker-a")
    repository.update_by_document(
        "upload__db1", status="failed", stage="failed", error_code="invalid_encoding",
        expected_worker_id="worker-a")

    retried = repository.retry_failed(
        "job_db1", new_job_id="job_db2", max_attempts=3)

    assert retried["job_id"] == "job_db2"
    assert retried["job_status"] == "queued"
    assert retried["attempts"] == 0 and retried["max_attempts"] == 3
    assert repository.get_job("job_db1")["job_status"] == "failed"
    assert repository.get_by_document("upload__db1")["job_id"] == "job_db2"
    assert repository.list_pending_outbox() == ["job_db2"]

    # Redis 中迟到的旧消息只能读取旧任务，不能越过 job_id 领取新的 current job。
    assert repository.claim_by_job("job_db1", worker_id="stale-worker") is None
    assert repository.get_job("job_db2")["job_status"] == "queued"
    claimed = repository.claim_by_job("job_db2", worker_id="current-worker")
    assert claimed["job_id"] == "job_db2"
    assert claimed["worker_id"] == "current-worker"

    with pytest.raises(UploadError) as exc:
        repository.retry_failed("job_db2", new_job_id="job_db3", max_attempts=3)
    assert exc.value.code == "job_not_retryable"


def test_sent_but_unclaimed_outbox_is_reopened_for_dispatch(tmp_path):
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(_record())
    assert repository.begin_outbox_publish("job_db1") is True
    repository.mark_outbox_sent("job_db1", "celery-lost")
    with Session(repository.engine) as session, session.begin():
        outbox = session.scalar(select(OutboxRow).where(OutboxRow.job_id == "job_db1"))
        outbox.sent_at = utcnow() - timedelta(hours=2)

    assert repository.list_pending_outbox() == []
    assert repository.recover_unclaimed(stale_seconds=3600) == {"unclaimed_recovered": 1}
    assert repository.list_pending_outbox() == ["job_db1"]
    assert repository.get_job("job_db1")["celery_task_id"] is None


def test_fast_worker_claim_does_not_let_dispatcher_revert_outbox_state(tmp_path):
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(_record())

    assert repository.begin_outbox_publish("job_db1") is True
    repository.claim_by_job("job_db1", worker_id="fast-worker")
    repository.mark_outbox_sent("job_db1", "celery-fast")

    with Session(repository.engine) as session:
        outbox = session.scalar(select(OutboxRow).where(OutboxRow.job_id == "job_db1"))
        assert outbox.status == "consumed"
    assert repository.get_job("job_db1")["celery_task_id"] == "celery-fast"


def test_fast_worker_retry_does_not_let_dispatcher_cancel_backoff(tmp_path):
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(_record())

    assert repository.begin_outbox_publish("job_db1") is True
    repository.claim_by_job("job_db1", worker_id="fast-worker")
    repository.schedule_retry(
        "upload__db1", error_code="mineru_timeout", delay_seconds=60,
        expected_worker_id="fast-worker")
    repository.mark_outbox_sent("job_db1", "celery-fast-retry")

    with Session(repository.engine) as session:
        outbox = session.scalar(select(OutboxRow).where(OutboxRow.job_id == "job_db1"))
        assert outbox.status == "pending"
        assert outbox.sent_at is None
        assert outbox.next_attempt_at is not None
    record = repository.get_job("job_db1")
    assert record["job_status"] == "retrying"
    assert record["celery_task_id"] == "celery-fast-retry"
    assert repository.list_pending_outbox() == []


def test_outbox_publish_reservation_prevents_duplicate_dispatch(tmp_path):
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(_record())

    assert repository.begin_outbox_publish("job_db1") is True
    assert repository.begin_outbox_publish("job_db1") is False


def test_stale_outbox_publish_reservation_is_recovered(tmp_path):
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    repository.create(_record())
    assert repository.begin_outbox_publish("job_db1") is True
    with Session(repository.engine) as session, session.begin():
        outbox = session.scalar(select(OutboxRow).where(OutboxRow.job_id == "job_db1"))
        outbox.updated_at = utcnow() - timedelta(seconds=61)

    assert repository.recover_unclaimed(
        stale_seconds=3600, publishing_stale_seconds=60) == {"unclaimed_recovered": 1}
    assert repository.list_pending_outbox() == ["job_db1"]
