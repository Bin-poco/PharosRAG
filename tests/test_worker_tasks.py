"""Celery 摄取入口的任务身份和领取前重试测试。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import pharos.worker.tasks as tasks


def test_ingest_worker_executes_the_message_job_id(monkeypatch):
    calls = []

    class Repository:
        def heartbeat(self, job_id, worker_id):
            return True

    class Manager:
        def process_job(self, job_id, *, worker_id, retry_on_transient):
            calls.append((job_id, worker_id, retry_on_transient))
            return {"job_id": job_id, "job_status": "succeeded", "stage": "ready"}

    runtime = SimpleNamespace(
        cfg=SimpleNamespace(job_heartbeat_seconds=3600),
        repository=Repository(),
        upload_manager=Manager(),
    )
    monkeypatch.setattr(tasks, "get_runtime", lambda: runtime)

    result = tasks.ingest_document.run("job_current")

    assert result["job_id"] == "job_current"
    assert calls[0][0] == "job_current"
    assert calls[0][2] is True


def test_ingest_worker_retries_transient_failure_before_claim(monkeypatch):
    class RetryRequested(Exception):
        pass

    retry = {}

    def request_retry(*, exc, countdown):
        retry.update(exc=exc, countdown=countdown)
        raise RetryRequested

    monkeypatch.setattr(
        tasks, "get_runtime", lambda: (_ for _ in ()).throw(ConnectionError("db offline")))
    monkeypatch.setattr(tasks, "retry_delay_seconds", lambda attempt, job_id: 7)
    monkeypatch.setattr(tasks.ingest_document, "retry", request_retry)

    with pytest.raises(RetryRequested):
        tasks.ingest_document.run("job_waiting")

    assert isinstance(retry["exc"], ConnectionError)
    assert retry["countdown"] == 7
