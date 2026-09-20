"""Real PostgreSQL publication-lock check, isolated in a disposable schema.

Run inside the app container (uses its PHAROS_DATABASE_URL, prints no credentials):
    docker exec -i pharos-mac-app python - < scripts/check_publication_lock.py
Never touches the existing application's tables; drops only the schema it creates.
"""
from datetime import timedelta
import json
import os
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from pharos.ingestion import UploadError
from pharos.jobs.models import DocumentRow, IngestionJobRow, utcnow
from pharos.jobs.repository import SQLJobRepository


def main():
    url = make_url(os.environ["PHAROS_DATABASE_URL"])
    if url.get_backend_name() != "postgresql":
        raise SystemExit("This check requires PostgreSQL.")
    schema = "pharos_lock_check_" + uuid.uuid4().hex
    admin = create_engine(url)
    repository = None
    created = False
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            created = True
        repository = SQLJobRepository(
            url.update_query_dict({"options": f"-csearch_path={schema}"}), create_schema=True)
        now = utcnow().isoformat()
        repository.create({
            "document_id": "test_document", "job_id": "test_job",
            "tenant": "test", "owner": "test", "filename": "test.md",
            "content_type": "text/markdown", "source_format": "markdown",
            "size": 1, "sha256": "a" * 64, "access_scope": "private", "groups": [],
            "acl": {"tenant": "test", "allow": ["user:test"]}, "source_path": "/unused",
            "created_at": now, "max_attempts": 3,
        })
        claimed = repository.claim_by_job("test_job", worker_id="old-worker")

        def expire():
            with Session(repository.engine) as session, session.begin():
                session.get(IngestionJobRow, "test_job").heartbeat_at = utcnow() - timedelta(seconds=600)

        expire()
        with repository.publish_guard(claimed):
            # Both the recovery row and the lifecycle row must be protected.
            for model in (IngestionJobRow, DocumentRow):
                try:
                    with Session(repository.engine) as session, session.begin():
                        session.execute(select(model).with_for_update(nowait=True)).all()
                except OperationalError as exc:
                    assert getattr(exc.orig, "sqlstate", None) == "55P03"
                else:
                    raise AssertionError(f"{model.__name__} was not locked")
            assert repository.recover_stale(120) == {"recovered": 0, "failed": 0}
        assert repository.recover_stale(120) == {"recovered": 0, "failed": 0}
        expire()
        assert repository.recover_stale(120) == {"recovered": 1, "failed": 0}
        assert repository.claim_by_job("test_job", worker_id="new-worker")
        try:
            with repository.publish_guard(claimed):
                raise AssertionError("late worker entered publication")
        except UploadError as exc:
            assert exc.code == "lease_lost"
        print(json.dumps({"postgres_publication_lock": "passed",
                          "checks": ["job_and_document_locked", "recovery_skips_publishing",
                                     "heartbeat_refreshed", "late_worker_rejected"]}))
    finally:
        if repository is not None:
            repository.engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            print("isolated test schema removed; application tables untouched")
        admin.dispose()


if __name__ == "__main__":
    main()
