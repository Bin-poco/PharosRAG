"""单篇文档的解析、分块与索引流水线。"""
from __future__ import annotations

import json
import threading
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
                 embedder_factory=None):
        self.root = Path(root).expanduser().resolve()
        self.retriever = retriever
        self.mineru_client = mineru_client
        self.embedder_factory = embedder_factory or Embedder
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

    def run(self, record: dict, update_stage: StageCallback) -> dict:
        """处理一条已领取的任务，成功返回索引统计，失败原样抛给执行器。"""
        document_id = record["document_id"]
        source = Path(record["source_path"])
        title = Path(record["filename"]).stem
        parsed_dir = self._doc_dir(document_id) / "parsed"
        parsed_dir.mkdir(parents=True, exist_ok=True)
        layout = None

        if record.get("source_format") == "pdf":
            if self.mineru_client is None:
                raise MinerUError("mineru_unconfigured", "PDF 上传尚未配置 MinerU 客户端。")
            update_stage(stage="mineru_parsing")
            parsed = self.mineru_client.parse_pdf(source, parsed_dir, data_id=document_id)
            content = json.loads(parsed.content_list_path.read_text(encoding="utf-8"))
            if parsed.layout_path:
                layout = json.loads(parsed.layout_path.read_text(encoding="utf-8"))
            image_root = parsed.content_root
            parser_batch_id = parsed.batch_id
        else:
            try:
                markdown = source.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise UploadError("invalid_encoding", "Markdown 必须是 UTF-8 编码。") from exc
            content = markdown_to_content_list(markdown, title=title, source_url="")
            (parsed_dir / f"{document_id}_content_list.json").write_text(
                json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            image_root = parsed_dir
            parser_batch_id = None

        metadata = {
            "doc_id": document_id,
            "title": title,
            "source_format": record["source_format"],
            "content_sha256": record["sha256"],
            "original_filename": record["filename"],
        }
        (parsed_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        update_stage(stage="chunking", parser_batch_id=parser_batch_id)
        elements = from_mineru(content, layout)
        sample = "".join((element.text or "") for element in elements[:40])[:2000]
        result = Chunker().chunk(
            elements,
            doc_id=document_id,
            doc_type="technical_document",
            lang="ch" if any("\u4e00" <= c <= "\u9fff" for c in sample) else "en",
            doc_meta=metadata,
            acl=record["acl"],
        )
        update_stage(stage="embedding")
        stats = self._get_embedder().index_document(
            document_id, elements, result, image_root=str(image_root))
        return {
            **stats,
            "chunk_count": int(stats.get("indexed", len(result.chunks))),
            "parser_batch_id": parser_batch_id,
        }
