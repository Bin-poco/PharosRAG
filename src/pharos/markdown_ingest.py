"""Import a reproducible text-document corpus into Pharos' normalized parse format.

The core chunker consumes MinerU-style ``*_content_list.json`` files.  Technical
documentation is commonly published as Markdown or reStructuredText, so this
module provides a lightweight ingestion path without pretending either format
has PDF layout or page coordinates.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx


_DOC_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*(?:__[a-z0-9][a-z0-9_.-]*)?$", re.I)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+)$")
_TAB = re.compile(r'^\s*===\s+["\'](.+?)["\']\s*$')
_ADMONITION = re.compile(r'^\s*!!!\s+([\w-]+)(?:\s+["\'](.+?)["\'])?\s*$')
_SHORTCODE = re.compile(r"^\s*{{[%<].*[%>]}}\s*$")
_HEADING_ANCHOR = re.compile(r"\s*\{\s*#[^}]+}\s*$")
_RST_DIRECTIVE = re.compile(r"^\.\.\s+([\w-]+)::\s*(.*)$")
_RST_TARGET = re.compile(r"^\.\.\s+_[^:]+:\s*(.*)$")
_RST_LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|#\.\s+)(.+)$")
_RST_HEADING_CHARS = set("=-~^\"'+*#:_`")
_SOURCE_FORMATS = {"markdown": ".md", "rst": ".rst"}
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


def rst_to_content_list(text: str, *, title: str, source_url: str = "") -> list[dict]:
    """Convert common reStructuredText constructs to Chunker elements.

    This is intentionally a semantic text normalizer rather than a full Sphinx
    renderer. It preserves headings, prose, lists, admonitions and code blocks,
    while dropping link targets and directive options that add no retrieval value.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    elements: list[dict] = [
        {"type": "text", "text": title, "text_level": 1, "page_idx": 0},
    ]
    if source_url:
        elements.append({"type": "text", "text": f"Canonical source: {source_url}", "page_idx": 0})
    paragraph: list[str] = []
    list_items: list[str] = []
    heading_styles: dict[str, int] = {}

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

    def flush_all() -> None:
        flush_paragraph()
        flush_list()

    def indented_block(start: int) -> tuple[list[str], int]:
        """Return one directive body with its common indentation removed."""
        end = start
        block: list[str] = []
        while end < len(lines):
            raw = lines[end]
            if raw.strip() and not raw[:1].isspace():
                break
            block.append(raw)
            end += 1
        nonblank = [len(value) - len(value.lstrip()) for value in block if value.strip()]
        indent = min(nonblank) if nonblank else 0
        return [value[indent:] if value.strip() else "" for value in block], end

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        # RST headings use an underline (and occasionally an overline) made from
        # one repeated punctuation character. Assign levels by first appearance,
        # matching Sphinx's document-local heading convention.
        if stripped and i + 1 < len(lines):
            underline = lines[i + 1].strip()
            if (len(underline) >= 3 and len(set(underline)) == 1
                    and underline[0] in _RST_HEADING_CHARS):
                flush_all()
                style = underline[0]
                level = heading_styles.setdefault(style, min(len(heading_styles) + 1, 6))
                elements.append({
                    "type": "text", "text": stripped, "text_level": level, "page_idx": 0,
                })
                i += 2
                continue

        # Overline+underline titles have a punctuation-only line before the title;
        # the next iteration recognizes the title via its underline.
        if (len(stripped) >= 3 and len(set(stripped)) == 1
                and stripped[0] in _RST_HEADING_CHARS):
            flush_all()
            i += 1
            continue

        if _RST_TARGET.match(stripped):
            flush_all()
            i += 1
            continue

        directive = _RST_DIRECTIVE.match(stripped)
        if directive:
            flush_all()
            name, argument = directive.groups()
            body, next_i = indented_block(i + 1)
            body = [value for value in body if not value.lstrip().startswith(":")]
            body_text = "\n".join(body).strip()
            if name in {"code-block", "sourcecode", "code"}:
                if body_text:
                    prefix = f"Code ({argument}):\n" if argument else "Code:\n"
                    elements.append({"type": "text", "text": prefix + body_text, "page_idx": 0})
            elif name in {"note", "warning", "tip", "important", "caution"}:
                elements.append({
                    "type": "text", "text": name.replace("-", " ").title(),
                    "text_level": 4, "page_idx": 0,
                })
                value = " ".join(part.strip() for part in ([argument] + body) if part.strip())
                if value:
                    elements.append({"type": "text", "text": value, "page_idx": 0})
            elif name not in {"contents", "include", "toctree"}:
                value = " ".join(part.strip() for part in ([argument] + body) if part.strip())
                if value:
                    elements.append({"type": "text", "text": value, "page_idx": 0})
            i = next_i
            continue

        item = _RST_LIST_ITEM.match(line)
        if item:
            flush_paragraph()
            list_items.append(item.group(1).strip())
            i += 1
            continue
        if list_items and line[:1].isspace() and stripped:
            list_items[-1] += " " + stripped
            i += 1
            continue
        if not stripped:
            flush_all()
            i += 1
            continue
        if stripped.startswith(".."):
            flush_all()
            i += 1
            continue
        flush_list()
        paragraph.append(stripped)
        i += 1

    flush_all()
    return elements


def _download_text(url: str, timeout: float, attempts: int = 3) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise MarkdownCorpusError(f"只允许 HTTPS 文档源: {url}")
    candidates = [url]
    # 某些网络/代理会持续截断 raw.githubusercontent.com；GitHub 的 /raw/ 路径指向同一
    # owner/revision/path，作为固定版本的等价下载通道，不回退到会漂移的默认分支。
    raw_match = re.fullmatch(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.*)", url)
    if raw_match:
        owner, repo, revision, path = raw_match.groups()
        candidates.append(f"https://github.com/{owner}/{repo}/raw/{revision}/{path}")
    last_error: Exception | None = None
    for candidate in candidates:
        for attempt in range(max(1, attempts)):
            try:
                response = httpx.get(
                    candidate, headers={"User-Agent": "PharosRAG-corpus-builder/1.0"},
                    follow_redirects=True, timeout=timeout)
                response.raise_for_status()
                return response.content.decode("utf-8")
            except (httpx.HTTPError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt + 1 < max(1, attempts):
                    time.sleep(0.25 * (2 ** attempt))
    raise MarkdownCorpusError(
        f"下载文档失败({type(last_error).__name__}): {url}") from last_error


def import_manifest(manifest_path: str | Path, dest: str | Path, *, timeout: float = 30.0,
                    only: str | None = None) -> int:
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
        source_format = str(doc.get("source_format") or "markdown").lower()
        if not _DOC_ID.fullmatch(doc_id):
            raise MarkdownCorpusError(f"非法 doc_id: {doc_id!r}")
        if doc_id in seen:
            raise MarkdownCorpusError(f"重复 doc_id: {doc_id}")
        if only and not doc_id.startswith(only):
            seen.add(doc_id)
            continue
        if not title or not raw_url or not source_url:
            raise MarkdownCorpusError(f"{doc_id}: title/raw_url/source_url 均为必填")
        if source_format not in _SOURCE_FORMATS:
            raise MarkdownCorpusError(f"{doc_id}: 不支持 source_format={source_format!r}")
        seen.add(doc_id)

        source_text = _download_text(raw_url, timeout)
        converter = markdown_to_content_list if source_format == "markdown" else rst_to_content_list
        content = converter(source_text, title=title, source_url=source_url)
        output_dir = dest / doc_id
        output_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        metadata = {key: doc[key] for key in _SAFE_META_KEYS if doc.get(key)}
        metadata.update({
            "doc_id": doc_id,
            "content_sha256": digest,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source_format": source_format,
            "page_scheme": "not_applicable",
        })
        source_name = "source" + _SOURCE_FORMATS[source_format]
        (output_dir / source_name).write_text(source_text, encoding="utf-8")
        (output_dir / f"{doc_id}_content_list.json").write_text(
            json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        imported += 1
        print(f"  [{imported:2d}] {doc_id}: {len(content)} elements, sha256={digest[:12]}", flush=True)
    if only and not imported:
        raise MarkdownCorpusError(f"--only 未匹配任何文档: {only}")
    return imported
