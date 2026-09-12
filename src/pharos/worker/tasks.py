"""Celery 任务入口：消息只携带 job_id，其余可信状态从数据库读取。"""
from __future__ import annotations

from .celery_app import app
from .runtime import get_dispatcher, get_runtime


@app.task(bind=True, name="pharos.ingest_document")
def ingest_document(self, job_id: str):
    runtime = get_runtime()
    record = runtime.repository.get_job(job_id)
    if record is None:
        return {"status": "not_found"}
    return runtime.upload_manager.process(
        record["document_id"], worker_id=self.request.hostname or "celery-worker")


@app.task(name="pharos.dispatch_pending")
def dispatch_pending(limit: int = 100):
    return get_dispatcher().dispatch_pending(limit=limit)
