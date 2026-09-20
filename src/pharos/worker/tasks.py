"""Celery 任务入口：消息只携带 job_id，其余可信状态从数据库读取。"""
from __future__ import annotations

import logging
import threading
import uuid
from contextlib import contextmanager

from .. import config
from ..ingestion import is_transient_ingestion_error
from ..uploads import retry_delay_seconds
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


@app.task(bind=True, name="pharos.ingest_document", max_retries=None)
def ingest_document(self, job_id: str):
    task_id = self.request.id or "unknown-task"
    # 同一个 Celery 消息可能重投；每次执行必须有独立租约身份。
    worker_id = f"{self.request.hostname or 'celery-worker'}:{task_id}:{uuid.uuid4().hex}"
    log.info("ingestion task received: job=%s worker=%s", job_id, worker_id)
    try:
        runtime = get_runtime()
        with _heartbeat(runtime.repository, job_id, worker_id,
                        runtime.cfg.job_heartbeat_seconds):
            result = runtime.upload_manager.process_job(
                job_id, worker_id=worker_id, retry_on_transient=True)
    except Exception as exc:
        # 领取任务前 PostgreSQL/Qdrant 等基础设施暂时不可用时，业务状态还无法安全更新。
        # 让 Celery 保留同一个 job_id 无限退避重试，Outbox 对账仍作为消息丢失的第二道保险。
        if is_transient_ingestion_error(exc):
            delay = retry_delay_seconds(int(self.request.retries or 0) + 1, job_id)
            log.warning("ingestion pre-claim retry: job=%s delay=%ss", job_id, delay,
                        exc_info=True)
            raise self.retry(exc=exc, countdown=delay)
        raise
    log.info("ingestion task finished: job=%s status=%s stage=%s",
             job_id, (result or {}).get("job_status"), (result or {}).get("stage"))
    return result or {"status": "not_found"}


@app.task(name="pharos.dispatch_pending")
def dispatch_pending(limit: int = 100):
    return get_dispatcher().dispatch_pending(limit=limit)


@app.task(name="pharos.recover_stale_jobs")
def recover_stale_jobs(limit: int = 100):
    dispatcher = get_dispatcher()
    cfg = config.from_env()
    unclaimed = dispatcher.repository.recover_unclaimed(
        cfg.job_dispatch_stale_seconds, limit=limit,
        publishing_stale_seconds=cfg.job_publish_stale_seconds)
    recovered = dispatcher.repository.recover_stale(cfg.job_stale_seconds, limit=limit)
    dispatched = dispatcher.dispatch_pending(limit=limit)
    return {**unclaimed, **recovered,
            **{f"dispatch_{key}": value for key, value in dispatched.items()}}
