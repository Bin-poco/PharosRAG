"""MinerU 单文档客户端：协议、产物定位与安全解压。"""
from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest

from embedder.embed import Embedder
from pharos.mineru import MinerUClient, MinerUError


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    return output.getvalue()


def test_parse_pdf_calls_mineru_and_finds_structured_output(tmp_path):
    content = json.dumps([
        {"type": "text", "text": "PDF 标题", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "正文证据", "page_idx": 0},
    ], ensure_ascii=False).encode()
    archive = _zip_bytes({
        "result/demo_content_list.json": content,
        "result/layout.json": b'{"pdf_info": []}',
        "result/images/chart.png": b"image",
    })
    seen = {"put": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v4/file-urls/batch":
            assert request.headers["authorization"] == "Bearer token"
            body = json.loads(request.content)
            assert body["model_version"] == "vlm" and body["files"][0]["data_id"] == "doc-1"
            return httpx.Response(200, json={"code": 0, "data": {
                "batch_id": "batch-1", "file_urls": ["https://upload.test/presigned"]}})
        if request.url.host == "upload.test":
            assert "authorization" not in request.headers
            assert request.content.startswith(b"%PDF-")
            seen["put"] = True
            return httpx.Response(200)
        if request.url.path.endswith("/extract-results/batch/batch-1"):
            return httpx.Response(200, json={"code": 0, "data": {"extract_result": [{
                "data_id": "doc-1", "state": "done", "full_zip_url": "https://cdn.test/result.zip"
            }]}})
        if request.url.host == "cdn.test":
            return httpx.Response(200, content=archive)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = MinerUClient(
        token="token", poll_seconds=0,
        client_factory=lambda: httpx.Client(transport=transport), sleep=lambda _: None)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nfixture")
    result = client.parse_pdf(source, tmp_path / "parsed", data_id="doc-1")

    assert seen["put"] is True
    assert result.batch_id == "batch-1"
    assert result.content_list_path.name == "demo_content_list.json"
    assert result.layout_path and result.layout_path.name == "layout.json"
    assert (result.content_root / "images" / "chart.png").is_file()


def test_parse_pdf_requires_token(tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7")
    with pytest.raises(MinerUError) as exc:
        MinerUClient(token="").parse_pdf(source, tmp_path / "out", data_id="d")
    assert exc.value.code == "mineru_unconfigured"


def test_safe_extract_rejects_path_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    archive.write_bytes(_zip_bytes({"../escape.txt": b"owned"}))
    client = MinerUClient(token="token")
    with pytest.raises(MinerUError) as exc:
        client._safe_extract(archive, tmp_path / "out")
    assert exc.value.code == "mineru_archive_unsafe"
    assert not (tmp_path / "escape.txt").exists()


def test_embedder_rejects_image_paths_outside_document_root(tmp_path):
    root = tmp_path / "parsed"
    root.mkdir()
    inside = root / "chart.png"
    inside.write_bytes(b"image")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")

    assert Embedder._safe_image_path(str(root), "chart.png") == str(inside.resolve())
    assert Embedder._safe_image_path(str(root), "../secret.txt") is None
    assert Embedder._safe_image_path(str(root), str(outside)) is None
