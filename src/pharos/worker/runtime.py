"""Worker 进程内惰性复用 Qdrant、远程推理客户端和任务仓储。"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from .. import config, engine
from ..ingestion import build_mineru_client
from ..jobs import CeleryJobDispatcher, SQLJobRepository
from ..uploads import DocumentUploadManager
from .celery_app import app


@dataclass
class WorkerRuntime:
    cfg: object
    repository: SQLJobRepository
    upload_manager: DocumentUploadManager
    dispatcher: CeleryJobDispatcher


_runtime = None
_lock = threading.Lock()
_dispatcher = None


def get_runtime() -> WorkerRuntime:
    global _runtime
    if _runtime is not None:
        return _runtime
    with _lock:
        if _runtime is not None:
            return _runtime
        cfg = config.from_env()
        if not cfg.database_url or not cfg.redis_url:
            raise RuntimeError("Celery Worker 需要 PHAROS_DATABASE_URL 和 PHAROS_REDIS_URL。")
        repository = SQLJobRepository(cfg.database_url)
        retriever = engine.build_retriever(cfg)
        upload_root = cfg.upload_dir or os.path.join(cfg.index_dir, "uploads")
        manager = DocumentUploadManager(
            upload_root, retriever, max_bytes=cfg.max_upload_bytes,
            mineru_client=build_mineru_client(cfg), repository=repository,
            max_attempts=cfg.job_max_attempts)
        _runtime = WorkerRuntime(
            cfg=cfg,
            repository=repository,
            upload_manager=manager,
            dispatcher=CeleryJobDispatcher(repository, app),
        )
        return _runtime


def get_dispatcher() -> CeleryJobDispatcher:
    """Beat 只需数据库和 broker，不应为一次 Outbox 扫描初始化检索器。"""
    global _dispatcher
    if _dispatcher is not None:
        return _dispatcher
    with _lock:
        if _dispatcher is None:
            cfg = config.from_env()
            if not cfg.database_url or not cfg.redis_url:
                raise RuntimeError("Outbox dispatcher 需要数据库和 Redis 配置。")
            _dispatcher = CeleryJobDispatcher(SQLJobRepository(cfg.database_url), app)
        return _dispatcher
