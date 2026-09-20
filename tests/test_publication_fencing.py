"""Late workers must not publish vectors, sidecars, or parsed files."""
from datetime import timedelta
import io
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy.orm import Session

from embedder import Embedder
from embedder.config import EmbedConfig
from pharos.jobs.models import IngestionJobRow, utcnow
from pharos.jobs.repository import SQLJobRepository, FileJobRepository
from pharos.uploads import DocumentUploadManager, UploadError
from tests.test_jobs import _record
from tests.test_uploads import UPLOADER


@pytest.mark.parametrize("kind", ["file", "sql"])
@pytest.mark.parametrize("changed", ["job_id", "worker_id", "attempts", "job_status"])
def test_publish_requires_exact_execution(tmp_path, kind, changed):
    repo = (FileJobRepository(tmp_path / "uploads") if kind == "file" else
            SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True))
    repo.create(_record())
    claimed = repo.claim_by_job("job_db1", worker_id="worker-a")
    with repo.publish_guard(claimed):
        pass
    stale = dict(claimed)
    if changed == "job_status":
        repo.update_by_document(claimed["document_id"], status="failed")
    else:
        stale[changed] = -1 if changed == "attempts" else "stale"
    with pytest.raises(UploadError, match="执行权"):
        with repo.publish_guard(stale):
            pytest.fail("stale execution entered publication")


@pytest.mark.parametrize("action", ["reclaim", "delete", "new_job"])
def test_late_encoder_cannot_overwrite_or_resurrect_document(tmp_path, action):
    repo = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    events = []

    class Store:
        def ensure_collection(self): pass
        def delete_by_doc(self, doc_id): events.append("delete")
        def upsert(self, points): events.append("upsert")

    class Dense:
        def encode_text(self, texts):
            # Inject a lost lease while encoding, after the last stage check.
            with Session(repo.engine) as session, session.begin():
                job = session.get(IngestionJobRow, created["job_id"])
                job.heartbeat_at = utcnow() - timedelta(seconds=600)
            repo.recover_stale(stale_seconds=120)
            replacement = repo.claim_by_job(created["job_id"], worker_id="worker-b")
            assert replacement
            if action != "reclaim":
                repo.update_by_document(created["document_id"], status="ready",
                                        expected_worker_id="worker-b")
                if action == "delete":
                    manager.delete_document(created["document_id"])
                    events.clear()  # The legitimate deletion is not a stale write.
                else:
                    repo.enqueue_reindex(created["document_id"], new_job_id="job_next",
                                         max_attempts=3)
                    repo.claim_by_job("job_next", worker_id="worker-c")
            return np.array([[1.0, 0.0] for _ in texts])

    cfg = EmbedConfig(sidecar_dir=str(tmp_path / "sidecars"), dense_dim=2)
    manager = DocumentUploadManager(
        str(tmp_path / "uploads"), SimpleNamespace(cfg=cfg, store=Store(), dense=Dense()),
        repository=repo)
    created = manager.create(io.BytesIO(b"One evidence paragraph."), filename="guide.md",
                             content_type="text/markdown", identity=UPLOADER,
                             access_scope="private", groups=[])
    doc_dir = tmp_path / "uploads" / created["document_id"]
    parsed = doc_dir / "parsed"
    parsed.mkdir()
    (parsed / "old.txt").write_text("current parsed data")
    Path(cfg.sidecar_dir).mkdir()
    sidecar = Path(cfg.sidecar_dir) / f"{created['document_id']}.json"
    sidecar.write_text("current sidecar")
    manager.process_job(created["job_id"], worker_id="worker-a")

    assert events == [], "late worker must not delete or upsert vectors"
    if action == "delete":
        assert not doc_dir.exists()
        assert not sidecar.exists()
    else:
        assert sidecar.read_text() == "current sidecar"
        assert (parsed / "old.txt").read_text() == "current parsed data"
    assert not list(Path(cfg.sidecar_dir).glob("*.tmp"))
    assert not list(doc_dir.glob(".parsed-*"))


def test_parsing_does_not_publish_after_lease_loss(tmp_path):
    from pharos.ingestion.pipeline import IngestionPipeline
    record = _record()
    doc_dir = tmp_path / record["document_id"]
    doc_dir.mkdir()
    source = doc_dir / "source.md"
    source.write_text("Evidence")
    record["source_path"] = str(source)
    parsed = doc_dir / "parsed"
    parsed.mkdir()
    (parsed / "old").write_text("old")

    def reject_stage(**changes):
        raise UploadError("lease_lost", "lost")

    pipeline = IngestionPipeline(tmp_path, None, publish_guard=lambda _: pytest.fail("publish"))
    with pytest.raises(UploadError):
        pipeline.run(record, reject_stage)
    assert (parsed / "old").read_text() == "old"
    assert not list(doc_dir.glob(".parsed-*"))


def test_sidecar_preparations_use_distinct_paths(tmp_path):
    from chunker import Chunker
    embedder = object.__new__(Embedder)
    embedder.cfg = EmbedConfig(sidecar_dir=str(tmp_path))
    result = Chunker().chunk([], doc_id="doc", doc_type="technical_document", lang="en")
    first, target = embedder._prepare_sidecar("doc", [], result)
    second, other_target = embedder._prepare_sidecar("doc", [], result)
    assert first != second and target == other_target
    assert Path(first).is_file() and Path(second).is_file()
