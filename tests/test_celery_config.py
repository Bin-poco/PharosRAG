"""Celery 队列隔离配置测试。"""

from pharos.worker.celery_app import build_celery_app


def test_control_tasks_are_isolated_from_ingestion_queue():
    app = build_celery_app()

    assert app.conf.task_routes["pharos.ingest_document"]["queue"] == "pharos.ingestion"
    assert app.conf.task_routes["pharos.dispatch_pending"]["queue"] == "pharos.control"
    assert app.conf.task_routes["pharos.recover_stale_jobs"]["queue"] == "pharos.control"
    for schedule in app.conf.beat_schedule.values():
        assert schedule["options"]["queue"] == "pharos.control"
