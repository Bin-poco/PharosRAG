"""Celery 应用配置；Redis 只承担 broker，不保存业务任务状态。"""
from __future__ import annotations

from celery import Celery

from .. import config


def build_celery_app(cfg=None) -> Celery:
    cfg = cfg or config.from_env()
    app = Celery("pharos", broker=cfg.redis_url or "memory://")
    app.conf.update(
        imports=("pharos.worker.tasks",),
        task_default_queue="pharos.ingestion",
        task_routes={
            "pharos.ingest_document": {"queue": "pharos.ingestion"},
            "pharos.dispatch_pending": {"queue": "pharos.control"},
            "pharos.recover_stale_jobs": {"queue": "pharos.control"},
        },
        task_serializer="json",
        accept_content=["json"],
        result_backend=None,
        task_ignore_result=True,
        task_track_started=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        broker_transport_options={"visibility_timeout": cfg.job_visibility_timeout},
        task_soft_time_limit=cfg.job_soft_time_limit,
        task_time_limit=cfg.job_time_limit,
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            "recover-pending-ingestion-outbox": {
                "task": "pharos.dispatch_pending",
                "schedule": 30.0,
                "args": (100,),
                "options": {"queue": "pharos.control"},
            },
            "recover-stale-ingestion-jobs": {
                "task": "pharos.recover_stale_jobs",
                "schedule": 30.0,
                "args": (100,),
                "options": {"queue": "pharos.control"},
            },
        },
    )
    return app


app = build_celery_app()
