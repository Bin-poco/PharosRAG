"""文档上传竖向闭环单测：权限派生、安全落盘、后台建库状态与 HTTP 绑定。"""
from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from _fakes import FakeRetriever, make_app, make_cfg
from pharos.identity import Identity
from pharos.jobs import SQLJobRepository
from pharos.mineru import MinerUResult
from pharos.uploads import DocumentUploadManager, UploadError, build_upload_acl


UPLOADER = Identity(name="alice", tenant="t1", principals=["g_eng"],
                    roles=["reader", "uploader"])
ADMIN = Identity(name="root", tenant="t1", principals=[], admin=True)
READER = Identity(name="bob", tenant="t1", principals=["g_eng"])


def test_upload_acl_is_server_derived_and_least_privilege():
    private = build_upload_acl(UPLOADER, "private", [])
    assert private == {"tenant": "t1", "allow": ["user:alice"],
                       "visibility": "restricted", "unset": False}

    team = build_upload_acl(UPLOADER, "restricted", ["g_eng"])
    assert team["allow"] == ["user:alice", "g_eng"]

    with pytest.raises(UploadError) as exc:
        build_upload_acl(UPLOADER, "restricted", ["g_finance"])
    assert exc.value.code == "group_forbidden"
    with pytest.raises(UploadError) as exc:
        build_upload_acl(UPLOADER, "tenant", [])
    assert exc.value.code == "tenant_publish_forbidden"

    public = build_upload_acl(ADMIN, "tenant", [])
    assert public["tenant"] == "t1" and public["visibility"] == "public"

    with pytest.raises(UploadError) as exc:
        build_upload_acl(READER, "private", [])
    assert exc.value.code == "upload_forbidden"


def test_upload_manager_persists_and_indexes_markdown(tmp_path, monkeypatch):
    import pharos.uploads as U

    indexed = {"calls": 0}

    class FakeEmbedder:
        def __init__(self, cfg, store=None, dense=None):
            pass

        def index_document(self, doc_id, elements, result, image_root):
            indexed["calls"] += 1
            indexed.update(doc_id=doc_id, elements=elements, result=result, image_root=image_root)
            return {"indexed": len(result.chunks)}

    monkeypatch.setattr(U, "Embedder", FakeEmbedder)
    retriever = SimpleNamespace(cfg=object(), store=object(), dense=object())
    manager = DocumentUploadManager(str(tmp_path / "uploads"), retriever, max_bytes=1024)
    record = manager.create(io.BytesIO("# Docker\n\nVolume 用于持久化。".encode()),
                            filename="guide.md", content_type="text/markdown",
                            identity=UPLOADER, access_scope="private", groups=[])

    assert record["status"] == "queued" and "source_path" not in record
    manager.process(record["document_id"])
    manager.process(record["document_id"])  # 重复调度幂等:已 ready 不再建库
    job = manager.get_job(record["job_id"])
    assert job["status"] == "ready" and job["stage"] == "ready" and job["chunk_count"] > 0
    assert indexed["calls"] == 1
    assert indexed["result"].chunks[0].acl["tenant"] == "t1"
    parsed = tmp_path / "uploads" / record["document_id"] / "parsed"
    assert list(parsed.glob("*_content_list.json"))
    assert json.loads((parsed / "metadata.json").read_text())["original_filename"] == "guide.md"


def test_upload_manager_rejects_unsupported_empty_and_oversize(tmp_path):
    manager = DocumentUploadManager(str(tmp_path / "uploads"), SimpleNamespace(), max_bytes=4)
    for stream, name, code in [
        (io.BytesIO(b"x"), "a.docx", "unsupported_type"),
        (io.BytesIO(b""), "a.md", "empty_file"),
        (io.BytesIO(b"12345"), "a.md", "file_too_large"),
    ]:
        with pytest.raises(UploadError) as exc:
            manager.create(stream, filename=name, content_type=None, identity=UPLOADER,
                           access_scope="private", groups=[])
        assert exc.value.code == code

    with pytest.raises(UploadError) as exc:
        manager.create(io.BytesIO(b"nope"), filename="fake.pdf", content_type="application/pdf",
                       identity=UPLOADER, access_scope="private", groups=[])
    assert exc.value.code == "invalid_pdf"


def test_upload_manager_parses_pdf_with_mineru_then_indexes(tmp_path, monkeypatch):
    import pharos.uploads as U

    indexed = {}

    class FakeEmbedder:
        def __init__(self, cfg, store=None, dense=None):
            pass

        def index_document(self, doc_id, elements, result, image_root):
            indexed.update(doc_id=doc_id, elements=elements, chunks=result.chunks,
                           image_root=image_root)
            return {"indexed": len(result.chunks)}

    class FakeMinerU:
        def parse_pdf(self, source, dest, *, data_id):
            output = dest / "result"
            output.mkdir(parents=True)
            content = [
                {"type": "text", "text": "PDF 手册", "text_level": 1, "page_idx": 0},
                {"type": "text", "text": "Volume 用于持久化。", "page_idx": 1},
            ]
            content_path = output / "manual_content_list.json"
            content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
            return MinerUResult(batch_id="batch-1", content_list_path=content_path,
                                layout_path=None, content_root=output)

    monkeypatch.setattr(U, "Embedder", FakeEmbedder)
    retriever = SimpleNamespace(cfg=object(), store=object(), dense=object())
    manager = DocumentUploadManager(str(tmp_path / "uploads"), retriever,
                                    mineru_client=FakeMinerU())
    record = manager.create(io.BytesIO(b"%PDF-1.7\nfixture"), filename="manual.pdf",
                            content_type="application/pdf", identity=UPLOADER,
                            access_scope="private", groups=[])
    manager.process(record["document_id"])

    job = manager.get_job(record["job_id"])
    assert job["status"] == "ready" and job["source_format"] == "pdf"
    assert job["parser_batch_id"] == "batch-1"
    assert indexed["doc_id"] == record["document_id"]
    assert indexed["elements"][1].page == 1
    assert indexed["image_root"].endswith("/parsed/result")


def test_pdf_upload_is_rejected_before_queue_when_mineru_is_unconfigured(tmp_path):
    class UnconfiguredMinerU:
        configured = False

    manager = DocumentUploadManager(str(tmp_path / "uploads"), SimpleNamespace(),
                                    mineru_client=UnconfiguredMinerU())
    with pytest.raises(UploadError) as exc:
        manager.create(io.BytesIO(b"%PDF-1.7\nfixture"), filename="manual.pdf",
                       content_type="application/pdf", identity=UPLOADER,
                       access_scope="private", groups=[])
    assert exc.value.code == "mineru_unconfigured"
    assert not list((tmp_path / "uploads").glob("upload__*"))


def test_transient_pipeline_failure_is_scheduled_for_retry(tmp_path):
    repository = SQLJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}", create_schema=True)
    manager = DocumentUploadManager(
        str(tmp_path / "uploads"), SimpleNamespace(), repository=repository, max_attempts=3)
    record = manager.create(
        io.BytesIO(b"# Retry"), filename="retry.md", content_type="text/markdown",
        identity=UPLOADER, access_scope="private", groups=[])

    class FailingPipeline:
        def run(self, record, update_stage):
            raise ConnectionError("temporary inference outage")

    manager._pipeline = FailingPipeline()
    result = manager.process(
        record["document_id"], worker_id="worker-a", retry_on_transient=True)

    assert result["job_status"] == "retrying"
    assert result["status"] == "queued"
    assert result["stage"] == "waiting_retry"
    assert result["attempts"] == 1


class FakeUploadManager:
    def __init__(self):
        self.records = {}
        self.processed = []

    def create(self, stream, *, filename, content_type, identity, access_scope, groups):
        acl = build_upload_acl(identity, access_scope, groups)
        record = {"document_id": "upload__1", "job_id": "job_1", "tenant": identity.tenant,
                  "owner": identity.name, "filename": filename, "size": len(stream.read()),
                  "sha256": "abc", "access_scope": access_scope, "groups": groups,
                  "status": "queued", "stage": "uploaded", "chunk_count": 0,
                  "error_code": None, "created_at": "now", "updated_at": "now", "acl": acl}
        self.records["job_1"] = record
        return {k: v for k, v in record.items() if k != "acl"}

    def process(self, document_id):
        self.processed.append(document_id)

    def get_job(self, job_id):
        record = self.records.get(job_id)
        return {k: v for k, v in record.items() if k != "acl"} if record else None

    def retry_job(self, job_id):
        record = dict(self.records[job_id])
        if record.get("job_status", record["status"]) != "failed":
            raise UploadError("job_not_retryable", "只有失败任务可以手动重试。")
        record.update(job_id="job_2", status="queued", job_status="queued",
                      stage="uploaded", attempts=0, error_code=None)
        self.records["job_2"] = record
        return {k: v for k, v in record.items() if k != "acl"}


def test_upload_http_requires_role_and_job_is_owner_scoped():
    uploader = Identity(name="alice", tenant="t1", principals=["g_eng"], roles=["uploader"])
    other = Identity(name="mallory", tenant="t2", principals=[], admin=True)
    keys = {"a" * 20: uploader, "b" * 20: other}
    manager = FakeUploadManager()
    app = make_app(cfg=make_cfg(host="0.0.0.0"), keys=keys)
    app.state.upload_manager = manager
    with TestClient(app) as client:
        response = client.post(
            "/v1/documents", headers={"X-API-Key": "a" * 20},
            files={"file": ("guide.md", b"# Guide", "text/markdown")},
            data={"access_scope": "restricted", "groups": "g_eng"})
        assert response.status_code == 202 and response.json()["status"] == "accepted"
        assert response.json()["document_status"] == "queued"
        assert manager.processed == ["upload__1"]
        job = client.get("/v1/jobs/job_1", headers={"X-API-Key": "a" * 20})
        assert job.status_code == 200 and job.json()["status"] == "ok"
        assert job.json()["document_status"] == "queued"
        assert client.get("/v1/jobs/job_1", headers={"X-API-Key": "b" * 20}).status_code == 404


def test_upload_http_dispatches_to_queue_when_dispatcher_is_configured():
    uploader = Identity(name="alice", tenant="t1", principals=[], roles=["uploader"])
    manager = FakeUploadManager()

    class FakeDispatcher:
        jobs = []

        def dispatch(self, job_id):
            self.jobs.append(job_id)

    dispatcher = FakeDispatcher()
    app = make_app(cfg=make_cfg(host="0.0.0.0"), keys={"a" * 20: uploader},
                   task_dispatcher=dispatcher)
    app.state.upload_manager = manager
    with TestClient(app) as client:
        response = client.post(
            "/v1/documents", headers={"X-API-Key": "a" * 20},
            files={"file": ("guide.md", b"# Guide", "text/markdown")})

    assert response.status_code == 202
    assert dispatcher.jobs == ["job_1"]
    assert manager.processed == []


def test_failed_upload_can_be_manually_retried_as_a_new_job():
    uploader = Identity(name="alice", tenant="t1", principals=[], roles=["uploader"])
    manager = FakeUploadManager()
    manager.create(io.BytesIO(b"# Guide"), filename="guide.md", content_type="text/markdown",
                   identity=uploader, access_scope="private", groups=[])
    manager.records["job_1"].update(status="failed", job_status="failed", stage="failed")

    class FakeDispatcher:
        jobs = []

        def dispatch(self, job_id):
            self.jobs.append(job_id)

    dispatcher = FakeDispatcher()
    app = make_app(cfg=make_cfg(host="0.0.0.0"), keys={"a" * 20: uploader},
                   task_dispatcher=dispatcher)
    app.state.upload_manager = manager
    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs/job_1/retry", headers={"X-API-Key": "a" * 20})

    assert response.status_code == 202
    assert response.json()["job_id"] == "job_2"
    assert response.json()["previous_job_id"] == "job_1"
    assert dispatcher.jobs == ["job_2"]


def test_upload_http_reader_is_forbidden():
    reader = Identity(name="bob", tenant="t1", principals=["g_eng"])
    manager = FakeUploadManager()
    app = make_app(cfg=make_cfg(host="0.0.0.0"), keys={"r" * 20: reader})
    app.state.upload_manager = manager
    with TestClient(app) as client:
        response = client.post(
            "/v1/documents", headers={"X-API-Key": "r" * 20},
            files={"file": ("guide.md", b"# Guide", "text/markdown")})
    assert response.status_code == 403 and response.json()["status"] == "upload_forbidden"


def test_upload_http_pdf_reports_missing_mineru_before_accepting(tmp_path, monkeypatch):
    for name in ("MINERU_TOKEN", "MINERU_TOKEN_A", "MINERU_TOKEN_B", "MINERU_TOKEN_C"):
        monkeypatch.delenv(name, raising=False)
    uploader = Identity(name="alice", tenant="t1", principals=[], roles=["uploader"])
    app = make_app(cfg=make_cfg(host="0.0.0.0", upload_dir=str(tmp_path / "uploads")),
                   keys={"a" * 20: uploader})
    with TestClient(app) as client:
        response = client.post(
            "/v1/documents", headers={"X-API-Key": "a" * 20},
            files={"file": ("manual.pdf", b"%PDF-1.7\nfixture", "application/pdf")})
    assert response.status_code == 503
    assert response.json()["status"] == "mineru_unconfigured"
