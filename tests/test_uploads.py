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

    admin_managed_private = build_upload_acl(ADMIN, "private", [], owner="alice")
    assert admin_managed_private["allow"] == ["user:alice"]

    with pytest.raises(UploadError) as exc:
        build_upload_acl(READER, "private", [])
    assert exc.value.code == "upload_forbidden"


def test_upload_manager_persists_and_indexes_markdown(tmp_path, monkeypatch):
    import pharos.uploads as U

    indexed = {"calls": 0}

    class FakeEmbedder:
        def __init__(self, cfg, store=None, dense=None):
            pass

        def index_document(self, doc_id, elements, result, image_root, *, publish_guard):
            with publish_guard():
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


def test_upload_manager_rejects_metadata_that_exceeds_database_limits(tmp_path):
    manager = DocumentUploadManager(str(tmp_path / "uploads"), SimpleNamespace())

    with pytest.raises(UploadError) as exc:
        manager.create(
            io.BytesIO(b"# Guide"), filename=f"{'a' * 510}.md", content_type="text/markdown",
            identity=UPLOADER, access_scope="private", groups=[])
    assert exc.value.code == "filename_too_long"

    with pytest.raises(UploadError) as exc:
        manager.create(
            io.BytesIO(b"# Guide"), filename="guide.md", content_type="x" * 161,
            identity=UPLOADER, access_scope="private", groups=[])
    assert exc.value.code == "content_type_too_long"

    assert not list((tmp_path / "uploads").glob("upload__*"))


def test_upload_manager_parses_pdf_with_mineru_then_indexes(tmp_path, monkeypatch):
    import pharos.uploads as U

    indexed = {}

    class FakeEmbedder:
        def __init__(self, cfg, store=None, dense=None):
            pass

        def index_document(self, doc_id, elements, result, image_root, *, publish_guard):
            with publish_guard():
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
    assert "/.parsed-" in indexed["image_root"]  # 编码只读本次尝试的私有目录
    assert (tmp_path / "uploads" / record["document_id"] / "parsed" / "result").is_dir()


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
    result = manager.process_job(
        record["job_id"], worker_id="worker-a", retry_on_transient=True)

    assert result["job_status"] == "retrying"
    assert result["status"] == "queued"
    assert result["stage"] == "waiting_retry"
    assert result["attempts"] == 1


def test_upload_manager_reindexes_updates_access_and_soft_deletes(tmp_path):
    manager = DocumentUploadManager(str(tmp_path / "uploads"), SimpleNamespace())
    record = manager.create(
        io.BytesIO(b"# Guide"), filename="guide.md", content_type="text/markdown",
        identity=UPLOADER, access_scope="private", groups=[])
    manager.repository.update_by_document(
        record["document_id"], status="ready", stage="ready", chunk_count=2)

    class FakePipeline:
        deleted = []

        def delete_index(self, document_id):
            self.deleted.append(document_id)

    pipeline = FakePipeline()
    manager._pipeline = pipeline
    reindexed = manager.reindex_document(record["document_id"])
    assert reindexed["job_id"] != record["job_id"] and reindexed["status"] == "queued"
    assert (tmp_path / "uploads" / record["document_id"] / "source.md").is_file()

    manager.repository.update_by_document(
        record["document_id"], status="ready", stage="ready", chunk_count=2)
    restricted = manager.update_access(
        record["document_id"], identity=UPLOADER,
        access_scope="restricted", groups=["g_eng"])
    assert restricted["access_scope"] == "restricted"
    assert restricted["groups"] == ["g_eng"] and restricted["status"] == "queued"
    assert restricted["chunk_count"] == 0

    manager.repository.update_by_document(
        record["document_id"], status="ready", stage="ready", chunk_count=2)
    deleted = manager.delete_document(record["document_id"])
    assert deleted["status"] == "deleted" and deleted["chunk_count"] == 0
    assert pipeline.deleted == [record["document_id"], record["document_id"]]
    doc_dir = tmp_path / "uploads" / record["document_id"]
    assert (doc_dir / "record.json").is_file()  # File 仓储仍保留软删除审计。
    assert not (doc_dir / "source.md").exists()
    assert manager.list_documents(tenant="t1") == []
    assert manager.list_documents(tenant="t1", include_deleted=True)[0]["status"] == "deleted"


def test_upload_manager_marks_incomplete_delete_for_safe_retry(tmp_path):
    manager = DocumentUploadManager(str(tmp_path / "uploads"), SimpleNamespace())
    record = manager.create(
        io.BytesIO(b"# Guide"), filename="guide.md", content_type="text/markdown",
        identity=UPLOADER, access_scope="private", groups=[])
    manager.repository.update_by_document(
        record["document_id"], status="ready", stage="ready")

    class FailingPipeline:
        def delete_index(self, document_id):
            raise ConnectionError("qdrant unavailable")

    manager._pipeline = FailingPipeline()
    with pytest.raises(ConnectionError):
        manager.delete_document(record["document_id"])

    failed = manager.get_document(record["document_id"])
    assert failed["status"] == "delete_failed"
    assert (tmp_path / "uploads" / record["document_id"] / "source.md").is_file()


def test_access_update_rejects_busy_document_before_touching_index(tmp_path):
    manager = DocumentUploadManager(str(tmp_path / "uploads"), SimpleNamespace())
    record = manager.create(
        io.BytesIO(b"# Guide"), filename="guide.md", content_type="text/markdown",
        identity=UPLOADER, access_scope="private", groups=[])

    class FakePipeline:
        deleted = []

        def delete_index(self, document_id):
            self.deleted.append(document_id)

    pipeline = FakePipeline()
    manager._pipeline = pipeline
    with pytest.raises(UploadError) as exc:
        manager.update_access(
            record["document_id"], identity=UPLOADER,
            access_scope="restricted", groups=["g_eng"])
    assert exc.value.code == "document_busy"
    assert pipeline.deleted == []


def test_access_update_failure_is_persisted_and_retryable(tmp_path):
    manager = DocumentUploadManager(str(tmp_path / "uploads"), SimpleNamespace())
    record = manager.create(
        io.BytesIO(b"# Guide"), filename="guide.md", content_type="text/markdown",
        identity=UPLOADER, access_scope="private", groups=[])
    manager.repository.update_by_document(
        record["document_id"], status="ready", stage="ready")

    class FailingPipeline:
        def delete_index(self, document_id):
            raise ConnectionError("qdrant unavailable")

    manager._pipeline = FailingPipeline()
    with pytest.raises(ConnectionError):
        manager.update_access(
            record["document_id"], identity=UPLOADER,
            access_scope="restricted", groups=["g_eng"])

    failed = manager.get_document(record["document_id"])
    assert failed["status"] == "access_update_failed"
    assert failed["job_status"] == "failed"
    assert failed["error_code"] == "access_update_failed"
    assert failed["access_scope"] == "private"  # 旧索引删除失败时不提交新权限。


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

    def get_document(self, document_id):
        matches = [record for record in self.records.values()
                   if record["document_id"] == document_id]
        record = matches[-1] if matches else None
        return {k: v for k, v in record.items() if k != "acl"} if record else None

    def list_documents(self, *, tenant, owner=None, include_deleted=False, limit=100, offset=0):
        current = {}
        for record in self.records.values():
            current[record["document_id"]] = record
        records = [record for record in current.values()
                   if record["tenant"] == tenant
                   and (owner is None or record["owner"] == owner)
                   and (include_deleted or record["status"] != "deleted")]
        return [{k: v for k, v in record.items() if k != "acl"}
                for record in records[offset:offset + limit]]

    def reindex_document(self, document_id, **changes):
        current = self.get_document(document_id)
        if current["status"] in {"queued", "processing"}:
            raise UploadError("document_busy", "文档正在处理中，请稍后重试。")
        record = {**current, **{k: v for k, v in changes.items() if v is not None},
                  "job_id": "job_lifecycle", "status": "queued",
                  "job_status": "queued", "stage": "uploaded"}
        self.records[record["job_id"]] = record
        return dict(record)

    def update_access(self, document_id, *, identity, access_scope, groups):
        acl = build_upload_acl(identity, access_scope, groups)
        return self.reindex_document(
            document_id, access_scope=access_scope, groups=groups, acl=acl)

    def delete_document(self, document_id):
        current = self.get_document(document_id)
        current.update(status="deleted", chunk_count=0)
        self.records[current["job_id"]] = current
        return current


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


def test_upload_http_maps_transient_persistence_failure_to_retriable_503():
    uploader = Identity(name="alice", tenant="t1", principals=[], roles=["uploader"])

    class UnavailableUploadManager(FakeUploadManager):
        def create(self, stream, *, filename, content_type, identity, access_scope, groups):
            raise ConnectionError("database temporarily unavailable")

    app = make_app(cfg=make_cfg(host="0.0.0.0"), keys={"a" * 20: uploader})
    app.state.upload_manager = UnavailableUploadManager()
    with TestClient(app) as client:
        response = client.post(
            "/v1/documents", headers={"X-API-Key": "a" * 20},
            files={"file": ("guide.md", b"# Guide", "text/markdown")})

    assert response.status_code == 503
    assert response.json() == {
        "status": "backend_unavailable",
        "retriable": True,
        "hint": "上传任务暂时无法保存，请稍后重试。",
    }


def test_document_management_http_is_owner_scoped_and_dispatches_lifecycle_jobs():
    uploader = Identity(name="alice", tenant="t1", principals=["g_eng"], roles=["uploader"])
    same_tenant_other = Identity(
        name="bob", tenant="t1", principals=["g_eng"], roles=["uploader"])
    admin = Identity(name="root", tenant="t1", principals=[], admin=True)
    manager = FakeUploadManager()
    manager.create(io.BytesIO(b"# Guide"), filename="guide.md", content_type="text/markdown",
                   identity=uploader, access_scope="private", groups=[])
    manager.records["job_1"].update(status="ready", job_status="succeeded", stage="ready")

    class FakeDispatcher:
        jobs = []

        def dispatch(self, job_id):
            self.jobs.append(job_id)

    dispatcher = FakeDispatcher()
    app = make_app(
        cfg=make_cfg(host="0.0.0.0"),
        keys={"a" * 20: uploader, "b" * 20: same_tenant_other, "r" * 20: admin},
        task_dispatcher=dispatcher)
    app.state.upload_manager = manager
    with TestClient(app) as client:
        listed = client.get("/v1/uploads", headers={"X-API-Key": "a" * 20})
        assert listed.status_code == 200 and listed.json()["returned_n"] == 1
        assert client.get("/v1/uploads", headers={"X-API-Key": "b" * 20}).json()["returned_n"] == 0
        assert client.get("/v1/uploads", headers={"X-API-Key": "r" * 20}).json()["returned_n"] == 1
        assert client.post(
            "/v1/documents/upload__1/reindex",
            headers={"X-API-Key": "b" * 20}).status_code == 404

        reindexed = client.post(
            "/v1/documents/upload__1/reindex", headers={"X-API-Key": "a" * 20})
        assert reindexed.status_code == 202
        assert reindexed.json()["job_id"] == "job_lifecycle"
        assert dispatcher.jobs == ["job_lifecycle"]


def test_document_management_http_updates_access_and_soft_deletes():
    uploader = Identity(name="alice", tenant="t1", principals=["g_eng"], roles=["uploader"])
    manager = FakeUploadManager()
    manager.create(io.BytesIO(b"# Guide"), filename="guide.md", content_type="text/markdown",
                   identity=uploader, access_scope="private", groups=[])
    manager.records["job_1"].update(status="ready", job_status="succeeded", stage="ready")

    class FakeDispatcher:
        jobs = []

        def dispatch(self, job_id):
            self.jobs.append(job_id)

    app = make_app(cfg=make_cfg(host="0.0.0.0"), keys={"a" * 20: uploader},
                   task_dispatcher=FakeDispatcher())
    app.state.upload_manager = manager
    with TestClient(app) as client:
        changed = client.patch(
            "/v1/documents/upload__1/access", headers={"X-API-Key": "a" * 20},
            json={"access_scope": "restricted", "groups": ["g_eng"]})
        assert changed.status_code == 202
        assert changed.json()["access_scope"] == "restricted"

        manager.records["job_lifecycle"].update(
            status="ready", job_status="succeeded", stage="ready")
        deleted = client.delete(
            "/v1/documents/upload__1", headers={"X-API-Key": "a" * 20})
        assert deleted.status_code == 200
        assert deleted.json()["document_status"] == "deleted"
        assert client.get(
            "/v1/uploads", headers={"X-API-Key": "a" * 20}).json()["returned_n"] == 0
        assert client.get(
            "/v1/uploads?include_deleted=true",
            headers={"X-API-Key": "a" * 20}).json()["documents"][0]["status"] == "deleted"
