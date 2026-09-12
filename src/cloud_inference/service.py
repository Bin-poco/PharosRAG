"""DashScope-backed implementation of Pharos' remote inference contract.

The upstream project expects a private service exposing ``/embed``,
``/embed_image`` and ``/rerank``.  This adapter preserves that boundary while
replacing the CUDA-only local models with Alibaba Cloud Model Studio APIs.
"""
from __future__ import annotations

import base64
import math
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


DEFAULT_EMBEDDING_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)
DEFAULT_RERANK_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/"
    "text-rerank/text-rerank"
)


@dataclass(frozen=True)
class Settings:
    api_key: str
    embedding_url: str = DEFAULT_EMBEDDING_URL
    rerank_url: str = DEFAULT_RERANK_URL
    embedding_model: str = "qwen3-vl-embedding"
    rerank_model: str = "qwen3-vl-rerank"
    dense_dim: int = 1024
    timeout: float = 120.0
    image_root: str = "/data/parsed"
    max_image_bytes: int = 20 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            dense_dim = int(os.environ.get("CLOUD_DENSE_DIM", "1024"))
            timeout = float(os.environ.get("CLOUD_TIMEOUT", "120"))
            max_image_bytes = int(os.environ.get("CLOUD_MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))
        except ValueError as exc:
            raise RuntimeError("CLOUD_DENSE_DIM/CLOUD_TIMEOUT/CLOUD_MAX_IMAGE_BYTES 配置格式错误") from exc
        if dense_dim <= 0 or timeout <= 0 or max_image_bytes <= 0:
            raise RuntimeError("云推理数值配置必须大于 0")
        return cls(
            api_key=os.environ.get("DASHSCOPE_API_KEY", "").strip(),
            embedding_url=os.environ.get("DASHSCOPE_EMBEDDING_URL", DEFAULT_EMBEDDING_URL).strip(),
            rerank_url=os.environ.get("DASHSCOPE_RERANK_URL", DEFAULT_RERANK_URL).strip(),
            embedding_model=os.environ.get("CLOUD_EMBEDDING_MODEL", "qwen3-vl-embedding").strip(),
            rerank_model=os.environ.get("CLOUD_RERANK_MODEL", "qwen3-vl-rerank").strip(),
            dense_dim=dense_dim,
            timeout=timeout,
            image_root=os.environ.get("CLOUD_IMAGE_ROOT", "/data/parsed").strip(),
            max_image_bytes=max_image_bytes,
        )


class EmbedReq(BaseModel):
    texts: list[str] = Field(default_factory=list)
    instruction: str | None = None


class EmbedImageReq(BaseModel):
    image_paths: list[str] = Field(default_factory=list)
    instruction: str | None = None


class RerankReq(BaseModel):
    query: str = ""
    documents: list[str] = Field(default_factory=list)
    instruction: str | None = None


def _normalise(vector: list[float], expected_dim: int) -> list[float]:
    if len(vector) != expected_dim:
        raise ValueError(f"云端向量维度 {len(vector)} != 配置维度 {expected_dim}")
    norm = math.sqrt(sum(float(x) * float(x) for x in vector))
    if norm <= 1e-12:
        raise ValueError("云端返回零向量")
    return [float(x) / norm for x in vector]


def _ordered_vectors(data: dict[str, Any], expected: int, dense_dim: int) -> list[list[float]]:
    items = data.get("output", {}).get("embeddings")
    if not isinstance(items, list):
        raise ValueError("云端响应缺少 output.embeddings")
    ordered: list[list[float] | None] = [None] * expected
    for item in items:
        idx = item.get("index")
        vector = item.get("embedding")
        if not isinstance(idx, int) or not 0 <= idx < expected or not isinstance(vector, list):
            raise ValueError("云端 embedding 响应索引或向量格式错误")
        ordered[idx] = _normalise(vector, dense_dim)
    if any(vector is None for vector in ordered):
        raise ValueError(f"云端返回 {len(items)} 个向量，预期 {expected} 个")
    return [vector for vector in ordered if vector is not None]


def _ordered_scores(data: dict[str, Any], expected: int) -> list[float]:
    items = data.get("output", {}).get("results")
    if not isinstance(items, list):
        raise ValueError("云端响应缺少 output.results")
    ordered: list[float | None] = [None] * expected
    for item in items:
        idx = item.get("index")
        score = item.get("relevance_score")
        if not isinstance(idx, int) or not 0 <= idx < expected or not isinstance(score, (int, float)):
            raise ValueError("云端 rerank 响应索引或分数格式错误")
        ordered[idx] = float(score)
    if any(score is None for score in ordered):
        raise ValueError(f"云端返回 {len(items)} 个重排结果，预期 {expected} 个")
    return [score for score in ordered if score is not None]


def _image_data_uri(path: str, root: str, max_bytes: int) -> str:
    try:
        root_path = Path(root).resolve(strict=True)
        image_path = Path(path).resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"图片不存在或不可读: {path}") from exc
    if not image_path.is_file() or not image_path.is_relative_to(root_path):
        raise ValueError("图片路径必须位于 CLOUD_IMAGE_ROOT 内")
    size = image_path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"图片大小 {size} bytes 超过限制 {max_bytes} bytes")
    mime = mimetypes.guess_type(image_path.name)[0] or ""
    if not mime.startswith("image/"):
        raise ValueError(f"不支持的图片类型: {image_path.suffix or 'unknown'}")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def create_app(settings: Settings | None = None, client: httpx.Client | None = None) -> FastAPI:
    cfg = settings or Settings.from_env()
    http = client or httpx.Client(timeout=cfg.timeout)
    app = FastAPI(title="pharos-cloud-inference", version="0.1.0")

    def require_key() -> None:
        if not cfg.api_key:
            raise HTTPException(status_code=503, detail="DASHSCOPE_API_KEY 未配置")

    def post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        require_key()
        try:
            response = http.post(
                url,
                headers={"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("message") or exc.response.text
            except Exception:
                detail = exc.response.text
            raise HTTPException(status_code=502, detail=f"DashScope HTTP {exc.response.status_code}: {detail[:300]}") from exc
        except (httpx.TransportError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=f"DashScope 不可用: {type(exc).__name__}") from exc
        if data.get("code"):
            raise HTTPException(status_code=502, detail=f"DashScope {data['code']}: {str(data.get('message', ''))[:300]}")
        return data

    @app.get("/healthz")
    def healthz():
        return {
            "status": "ok",
            "service": "cloud-inference",
            "provider": "dashscope",
            "configured": bool(cfg.api_key),
            # RemoteDense uses these fields for its one-time model/dimension handshake.
            "model_dense": cfg.embedding_model,
            "full_dim": cfg.dense_dim,
        }

    @app.get("/readyz")
    def readyz():
        if not cfg.api_key:
            return JSONResponse({"status": "error", "detail": "DASHSCOPE_API_KEY 未配置"}, status_code=503)
        return {"status": "ready"}

    @app.post("/embed")
    def embed(req: EmbedReq):
        if not req.texts:
            return {"vectors": []}
        parameters: dict[str, Any] = {"dimension": cfg.dense_dim}
        if req.instruction:
            parameters["instruct"] = req.instruction
        data = post(cfg.embedding_url, {
            "model": cfg.embedding_model,
            "input": {"contents": [{"text": text} for text in req.texts]},
            "parameters": parameters,
        })
        try:
            return {"vectors": _ordered_vectors(data, len(req.texts), cfg.dense_dim)}
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/embed_image")
    def embed_image(req: EmbedImageReq):
        if not req.image_paths:
            return {"vectors": []}
        try:
            contents = [
                {"image": _image_data_uri(path, cfg.image_root, cfg.max_image_bytes)}
                for path in req.image_paths
            ]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        parameters: dict[str, Any] = {"dimension": cfg.dense_dim}
        if req.instruction:
            parameters["instruct"] = req.instruction
        data = post(cfg.embedding_url, {
            "model": cfg.embedding_model,
            "input": {"contents": contents},
            "parameters": parameters,
        })
        try:
            return {"vectors": _ordered_vectors(data, len(req.image_paths), cfg.dense_dim)}
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/rerank")
    def rerank(req: RerankReq):
        if not req.documents:
            return {"scores": []}
        parameters: dict[str, Any] = {
            "top_n": len(req.documents),
            "return_documents": False,
        }
        if req.instruction:
            parameters["instruct"] = req.instruction
        data = post(cfg.rerank_url, {
            "model": cfg.rerank_model,
            "input": {
                "query": {"text": req.query},
                "documents": [{"text": document} for document in req.documents],
            },
            "parameters": parameters,
        })
        try:
            return {"scores": _ordered_scores(data, len(req.documents))}
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return app


app = create_app()
