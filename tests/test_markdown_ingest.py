import json

import pytest

from pharos.indexer import load_doc_meta
from pharos.markdown_ingest import MarkdownCorpusError, markdown_to_content_list


def test_markdown_conversion_preserves_structure_and_code():
    source = """---
title: ignored front matter
---
# API { #api-anchor }

Intro paragraph.

- one
- two

```python
print("hello")
```
"""
    content = markdown_to_content_list(source, title="Official API", source_url="https://example.test/doc")
    assert content[0]["text"] == "Official API"
    assert any(item.get("text_level") == 1 and item["text"] == "API" for item in content)
    assert not any("api-anchor" in item.get("text", "") for item in content)
    assert any(item["type"] == "list" and item["list_items"] == ["one", "two"] for item in content)
    assert any("print(\"hello\")" in item.get("text", "") for item in content)
    assert not any("ignored front matter" in item.get("text", "") for item in content)


def test_load_doc_meta_keeps_provenance_and_drops_acl(tmp_path):
    metadata = {
        "title": "Docker Volumes",
        "source_url": "https://docs.docker.com/engine/storage/volumes/",
        "license": "Apache-2.0",
        "acl": {"visibility": "public"},
        "tenant": "poisoned",
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    result = load_doc_meta(str(tmp_path), "fallback")
    assert result["title"] == "Docker Volumes"
    assert result["source_url"].startswith("https://")
    assert "acl" not in result and "tenant" not in result


def test_invalid_metadata_fails_loudly(tmp_path):
    (tmp_path / "metadata.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="顶层必须是对象"):
        load_doc_meta(str(tmp_path), "fallback")


def test_manifest_rejects_unsafe_doc_id(tmp_path, monkeypatch):
    from pharos import markdown_ingest

    manifest = {"documents": [{
        "doc_id": "../escape", "title": "bad", "raw_url": "https://example.test/raw",
        "source_url": "https://example.test/doc",
    }]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(markdown_ingest, "_download_text", lambda *_: "# never")
    with pytest.raises(MarkdownCorpusError, match="非法 doc_id"):
        markdown_ingest.import_manifest(path, tmp_path / "out")


def test_download_retries_incomplete_response(monkeypatch):
    import httpx
    from pharos import markdown_ingest

    class _Response:
        content = b"# recovered"

        def raise_for_status(self):
            return None

    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError("incomplete body")
        return _Response()

    monkeypatch.setattr(markdown_ingest.httpx, "get", fake_get)
    monkeypatch.setattr(markdown_ingest.time, "sleep", lambda _seconds: None)
    assert markdown_ingest._download_text("https://example.test/doc.md", 1) == "# recovered"
    assert len(calls) == 2


def test_download_falls_back_to_github_raw_route(monkeypatch):
    import httpx
    from pharos import markdown_ingest

    class _Response:
        content = b"# complete"

        def raise_for_status(self):
            return None

    urls = []

    def fake_get(url, **kwargs):
        urls.append(url)
        if "raw.githubusercontent.com" in url:
            raise httpx.RemoteProtocolError("incomplete body")
        return _Response()

    monkeypatch.setattr(markdown_ingest.httpx, "get", fake_get)
    monkeypatch.setattr(markdown_ingest.time, "sleep", lambda _seconds: None)
    url = "https://raw.githubusercontent.com/acme/docs/abc123/guide.md"
    assert markdown_ingest._download_text(url, 1, attempts=2) == "# complete"
    assert urls == [url, url, "https://github.com/acme/docs/raw/abc123/guide.md"]


def test_manifest_only_downloads_matching_doc(tmp_path, monkeypatch):
    from pharos import markdown_ingest

    manifest = {"documents": [
        {"doc_id": "docker__volumes", "title": "Volumes",
         "raw_url": "https://example.test/volumes", "source_url": "https://example.test/v"},
        {"doc_id": "docker__bind_mounts", "title": "Bind mounts",
         "raw_url": "https://example.test/binds", "source_url": "https://example.test/b"},
    ]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    fetched = []
    monkeypatch.setattr(markdown_ingest, "_download_text",
                        lambda url, timeout: fetched.append(url) or "# Bind mounts")
    count = markdown_ingest.import_manifest(
        path, tmp_path / "out", only="docker__bind_mounts")
    assert count == 1 and fetched == ["https://example.test/binds"]
    assert (tmp_path / "out/docker__bind_mounts/metadata.json").exists()
    assert not (tmp_path / "out/docker__volumes").exists()
