"""将数据库 Outbox 中的摄取请求投递到 Celery。"""
from __future__ import annotations

import logging
import uuid


log = logging.getLogger("pharos")
INGEST_TASK = "pharos.ingest_document"


class CeleryJobDispatcher:
    def __init__(self, repository, celery_app):
        self.repository = repository
        self.celery_app = celery_app

    def dispatch(self, job_id: str) -> str:
        task_id = f"ingest_{uuid.uuid4().hex}"
        try:
            self.celery_app.send_task(INGEST_TASK, args=[job_id], task_id=task_id)
        except Exception:
            self.repository.mark_outbox_failed(job_id)
            raise
        self.repository.mark_outbox_sent(job_id, task_id)
        return task_id

    def dispatch_pending(self, limit: int = 100) -> dict:
        sent = failed = 0
        for job_id in self.repository.list_pending_outbox(limit=limit):
            try:
                self.dispatch(job_id)
                sent += 1
            except Exception:
                failed += 1
                log.warning("outbox publish failed: job=%s", job_id, exc_info=True)
        return {"sent": sent, "failed": failed}
