"""Import a reproducible Markdown corpus into Pharos' normalized parse format.

The core chunker consumes MinerU-style ``*_content_list.json`` files.  Technical
documentation is commonly published as Markdown, so this module provides a
lightweight, dependency-free ingestion path without pretending Markdown has PDF
layout or page coordinates.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


_DOC_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*(?:__[a-z0-9][a-z0-9_.-]*)?$", re.I)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+)$")
_TAB = re.compile(r'^\s*===\s+["\'](.+?)["\']\s*$')
_ADMONITION = re.compile(r'^\s*!!!\s+([\w-]+)(?:\s+["\'](.+?)["\'])?\s*$')
_SHORTCODE = re.compile(r"^\s*{{[%<].*[%>]}}\s*$")
_HEADING_ANCHOR = re.compile(r"\s*\{\s*#[^}]+}\s*$")
_SAFE_META_KEYS = {
    "title", "topic", "repository", "revision", "source_url", "license", "license_url"
}


class MarkdownCorpusError(ValueError):
    """The Markdown corpus manifest or a source document is invalid."""


def _strip_front_matter(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1:])
    return "\n".join(lines)


def markdown_to_content_list(text: str, *, title: str, source_url: str = "") -> list[dict]:
    """Convert Markdown into the subset of MinerU elements used by ``Chunker``.

    Markdown has no stable pages, so every element uses ``page_idx=0``. Headings,
    paragraphs, lists and fenced code blocks remain separate semantic elements.
    """
    lines = _strip_front_matter(text).split("\n")
    elements: list[dict] = [
        {"type": "text", "text": title, "text_level": 1, "page_idx": 0},
    ]
    if source_url:
        elements.append({"type": "text", "text": f"Canonical source: {source_url}", "page_idx": 0})
    paragraph: list[str] = []
    list_items: list[str] = []
    code_lines: list[str] = []
    in_code = False
    code_lang = ""

    def flush_paragraph() -> None:
        if paragraph:
            value = " ".join(part.strip() for part in paragraph if part.strip()).strip()
            if value:
                elements.append({"type": "text", "text": value, "page_idx": 0})
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            values = list(list_items)
            elements.append({
                "type": "list",
                "text": "\n".join(f"- {item}" for item in values),
                "list_items": values,
                "page_idx": 0,
            })
            list_items.clear()

    def flush_code() -> None:
        nonlocal code_lang
        value = "\n".join(code_lines).strip("\n")
        if value:
            prefix = f"Code ({code_lang}):\n" if code_lang else "Code:\n"
            elements.append({"type": "text", "text": prefix + value, "page_idx": 0})
        code_lines.clear()
        code_lang = ""

    for raw in lines:
        line = raw.rstrip()
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            if in_code:
                flush_code()
                in_code = False
            else:
                flush_paragraph()
                flush_list()
                marker = line.lstrip()
                code_lang = marker[3:].strip()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue

        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            heading_text = _HEADING_ANCHOR.sub("", heading.group(2)).strip()
            elements.append({
                "type": "text",
                "text": heading_text,
                "text_level": len(heading.group(1)),
                "page_idx": 0,
            })
            continue
        tab = _TAB.match(line)
        if tab:
            flush_paragraph()
            flush_list()
            elements.append({"type": "text", "text": tab.group(1), "text_level": 4, "page_idx": 0})
            continue
        admonition = _ADMONITION.match(line)
        if admonition:
            flush_paragraph()
            flush_list()
            label = admonition.group(2) or admonition.group(1).replace("-", " ").title()
            elements.append({"type": "text", "text": label, "text_level": 4, "page_idx": 0})
            continue
        item = _LIST_ITEM.match(line)
        if item:
            flush_paragraph()
            list_items.append(item.group(1).strip())
            continue
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue
        if _SHORTCODE.match(line) or line.lstrip().startswith("<!--"):
            flush_paragraph()
            flush_list()
            continue
        flush_list()
        paragraph.append(line.strip())

    if in_code:
        flush_code()
    flush_paragraph()
    flush_list()
    return elements


def _download_text(url: str, timeout: float) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise MarkdownCorpusError(f"只允许 HTTPS 文档源: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "PharosRAG-corpus-builder/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    return data.decode("utf-8")


def import_manifest(manifest_path: str | Path, dest: str | Path, *, timeout: float = 30.0) -> int:
    """Download all manifest documents and write normalized per-document directories."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise MarkdownCorpusError("manifest.documents 必须是非空数组")

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    imported = 0
    for doc in documents:
        if not isinstance(doc, dict):
            raise MarkdownCorpusError("manifest.documents 中每项必须是对象")
        doc_id = str(doc.get("doc_id") or "")
        title = str(doc.get("title") or "")
        raw_url = str(doc.get("raw_url") or "")
        source_url = str(doc.get("source_url") or "")
        if not _DOC_ID.fullmatch(doc_id):
            raise MarkdownCorpusError(f"非法 doc_id: {doc_id!r}")
        if doc_id in seen:
            raise MarkdownCorpusError(f"重复 doc_id: {doc_id}")
        if not title or not raw_url or not source_url:
            raise MarkdownCorpusError(f"{doc_id}: title/raw_url/source_url 均为必填")
        seen.add(doc_id)

        markdown = _download_text(raw_url, timeout)
        content = markdown_to_content_list(markdown, title=title, source_url=source_url)
        output_dir = dest / doc_id
        output_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        metadata = {key: doc[key] for key in _SAFE_META_KEYS if doc.get(key)}
        metadata.update({
            "doc_id": doc_id,
            "content_sha256": digest,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source_format": "markdown",
            "page_scheme": "not_applicable",
        })
        (output_dir / "source.md").write_text(markdown, encoding="utf-8")
        (output_dir / f"{doc_id}_content_list.json").write_text(
            json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        imported += 1
        print(f"  [{imported:2d}] {doc_id}: {len(content)} elements, sha256={digest[:12]}", flush=True)
    return imported
