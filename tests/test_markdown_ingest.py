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
