"""文档/任务关系数据库仓储测试。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pharos.jobs.models import OutboxRow
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

    claimed = first.claim_by_document("upload__db1", worker_id="worker-a")
    assert claimed["status"] == "processing"
    assert claimed["job_status"] == "running"
    assert claimed["attempts"] == 1
    assert claimed["worker_id"] == "worker-a"
    assert second.claim_by_document("upload__db1", worker_id="worker-b") is None

    first.update_by_document("upload__db1", stage="embedding")
    ready = first.update_by_document(
        "upload__db1", status="ready", stage="ready", chunk_count=4)
    assert ready["status"] == "ready"
    assert ready["job_status"] == "succeeded"
    assert ready["chunk_count"] == 4
    assert ready["finished_at"] is not None
