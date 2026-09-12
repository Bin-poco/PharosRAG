"""Celery 任务入口：消息只携带 job_id，其余可信状态从数据库读取。"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

from .. import config
from .celery_app import app
from .runtime import get_dispatcher, get_runtime


log = logging.getLogger("pharos")


@contextmanager
def _heartbeat(repository, job_id: str, worker_id: str, interval_seconds: int):
    """长时间解析期间续租；主任务退出时立即停止，不遗留后台线程。"""
    stopped = threading.Event()

    def beat() -> None:
        while not stopped.wait(max(1, int(interval_seconds))):
            try:
                if not repository.heartbeat(job_id, worker_id):
                    return
            except Exception:
                # 短暂数据库故障由 stale recovery 兜底，心跳线程不能杀死主任务。
                log.warning("job heartbeat failed: job=%s worker=%s", job_id, worker_id,
                            exc_info=True)

    thread = threading.Thread(target=beat, name=f"heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=2)


@app.task(bind=True, name="pharos.ingest_document")
def ingest_document(self, job_id: str):
    runtime = get_runtime()
    record = runtime.repository.get_job(job_id)
    if record is None:
        return {"status": "not_found"}
    task_id = self.request.id or "unknown-task"
    worker_id = f"{self.request.hostname or 'celery-worker'}:{task_id}"
    log.info("ingestion task received: job=%s doc=%s worker=%s",
             job_id, record["document_id"], worker_id)
    with _heartbeat(runtime.repository, job_id, worker_id,
                    runtime.cfg.job_heartbeat_seconds):
        result = runtime.upload_manager.process(
            record["document_id"], worker_id=worker_id, retry_on_transient=True)
    log.info("ingestion task finished: job=%s status=%s stage=%s",
             job_id, (result or {}).get("job_status"), (result or {}).get("stage"))
    return result


@app.task(name="pharos.dispatch_pending")
def dispatch_pending(limit: int = 100):
    return get_dispatcher().dispatch_pending(limit=limit)


@app.task(name="pharos.recover_stale_jobs")
def recover_stale_jobs(limit: int = 100):
    dispatcher = get_dispatcher()
    cfg = config.from_env()
    recovered = dispatcher.repository.recover_stale(cfg.job_stale_seconds, limit=limit)
    dispatched = dispatcher.dispatch_pending(limit=limit)
    return {**recovered, **{f"dispatch_{key}": value for key, value in dispatched.items()}}
