"""单篇文档的解析、分块与索引流水线。"""
from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from chunker import Chunker
from chunker.adapters.mineru import from_mineru
from embedder import Embedder

from ..markdown_ingest import markdown_to_content_list
from ..mineru import MinerUClient, MinerUError
from .errors import UploadError


StageCallback = Callable[..., dict]


class IngestionPipeline:
    """执行可复用的摄取业务，不负责领取任务或决定失败重试策略。"""

    def __init__(self, root: str | Path, retriever, *,
                 mineru_client: MinerUClient | None = None,
                 embedder_factory=None, publish_guard):
        self.root = Path(root).expanduser().resolve()
        self.retriever = retriever
        self.mineru_client = mineru_client
        self.embedder_factory = embedder_factory or Embedder
        self.publish_guard = publish_guard
        self._embedder = None
        self._lock = threading.Lock()

    def _doc_dir(self, document_id: str) -> Path:
        path = (self.root / document_id).resolve()
        if not path.is_relative_to(self.root):
            raise UploadError("invalid_doc_id", "非法 document id。")
        return path

    def _get_embedder(self):
        with self._lock:
            if self._embedder is None:
                # 复用 Retriever 已有 Store/Dense，避免重复创建 Qdrant 客户端或加载模型。
                self._embedder = self.embedder_factory(
                    self.retriever.cfg,
                    store=self.retriever.store,
                    dense=self.retriever.dense,
                )
            return self._embedder

    def delete_index(self, document_id: str) -> None:
        """删除一篇文档的 Qdrant points 与 sidecar；供生命周期管理复用。"""
        self._get_embedder().delete_document(document_id)

    def run(self, record: dict, update_stage: StageCallback) -> dict:
        """处理一条已领取的任务，成功返回索引统计，失败原样抛给执行器。"""
        document_id = record["document_id"]
        source = Path(record["source_path"])
        title = Path(record["filename"]).stem
        doc_dir = self._doc_dir(document_id)
        parsed_dir = doc_dir / "parsed"
        attempt = int(record.get("attempts", 1))
        attempt_dir = doc_dir / f".parsed-{record['job_id']}-{attempt}-{uuid.uuid4().hex}.tmp"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        layout = None
        try:
            if record.get("source_format") == "pdf":
                if self.mineru_client is None:
                    raise MinerUError("mineru_unconfigured", "PDF 上传尚未配置 MinerU 客户端。")
                update_stage(stage="mineru_parsing")
                parsed = self.mineru_client.parse_pdf(source, attempt_dir, data_id=document_id)
                content = json.loads(parsed.content_list_path.read_text(encoding="utf-8"))
                if parsed.layout_path:
                    layout = json.loads(parsed.layout_path.read_text(encoding="utf-8"))
                image_relative = parsed.content_root.relative_to(attempt_dir)
                parser_batch_id = parsed.batch_id
            else:
                try:
                    markdown = source.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    raise UploadError("invalid_encoding", "Markdown 必须是 UTF-8 编码。") from exc
                content = markdown_to_content_list(markdown, title=title, source_url="")
                (attempt_dir / f"{document_id}_content_list.json").write_text(
                    json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                image_relative = Path(".")
                parser_batch_id = None

            metadata = {
                "doc_id": document_id,
                "title": title,
                "source_format": record["source_format"],
                "content_sha256": record["sha256"],
                "original_filename": record["filename"],
            }
            (attempt_dir / "metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            update_stage(stage="chunking", parser_batch_id=parser_batch_id)
            elements = from_mineru(content, layout)
            sample = "".join((element.text or "") for element in elements[:40])[:2000]
            result = Chunker().chunk(
                elements, doc_id=document_id, doc_type="technical_document",
                lang="ch" if any("\u4e00" <= c <= "\u9fff" for c in sample) else "en",
                doc_meta=metadata, acl=record["acl"],
            )

            @contextmanager
            def publish():
                with self.publish_guard(record):
                    yield
                    # 只有当前执行的向量/sidecar 发布成功后，才替换正式解析目录。
                    shutil.rmtree(parsed_dir, ignore_errors=True)
                    os.replace(attempt_dir, parsed_dir)

            update_stage(stage="embedding")
            stats = self._get_embedder().index_document(
                document_id, elements, result, image_root=str(attempt_dir / image_relative),
                publish_guard=publish)
            return {**stats, "chunk_count": int(stats.get("indexed", len(result.chunks))),
                    "parser_batch_id": parser_batch_id}
        finally:
            shutil.rmtree(attempt_dir, ignore_errors=True)
