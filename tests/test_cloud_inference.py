from __future__ import annotations

import math

from fastapi.testclient import TestClient

from cloud_inference.service import Settings, create_app


class _Response:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _HTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return _Response(self.responses.pop(0))


def _settings(tmp_path, **changes):
    values = dict(api_key="test-key", dense_dim=2, image_root=str(tmp_path))
    values.update(changes)
    return Settings(**values)


def test_health_reports_model_contract_and_missing_key_is_not_ready(tmp_path):
    app = create_app(_settings(tmp_path, api_key=""), _HTTP([]))
    with TestClient(app) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")
    assert health.status_code == 200
    assert health.json()["model_dense"] == "qwen3-vl-embedding"
    assert health.json()["full_dim"] == 2
    assert health.json()["configured"] is False
    assert ready.status_code == 503


def test_embed_preserves_input_order_and_normalises_vectors(tmp_path):
    http = _HTTP([{
        "output": {"embeddings": [
            {"index": 1, "embedding": [0.0, 2.0]},
            {"index": 0, "embedding": [3.0, 4.0]},
        ]}
    }])
    app = create_app(_settings(tmp_path), http)
    with TestClient(app) as client:
        response = client.post("/embed", json={"texts": ["A", "B"], "instruction": "检索技术文档"})

    assert response.status_code == 200
    assert response.json()["vectors"] == [[0.6, 0.8], [0.0, 1.0]]
    payload = http.calls[0]["json"]
    assert payload["input"]["contents"] == [{"text": "A"}, {"text": "B"}]
    assert payload["parameters"] == {"dimension": 2, "instruct": "检索技术文档"}


def test_rerank_restores_scores_to_document_order(tmp_path):
    http = _HTTP([{
        "output": {"results": [
            {"index": 1, "relevance_score": 0.91},
            {"index": 0, "relevance_score": 0.12},
        ]}
    }])
    app = create_app(_settings(tmp_path), http)
    with TestClient(app) as client:
        response = client.post("/rerank", json={"query": "Q", "documents": ["D0", "D1"]})

    assert response.status_code == 200
    assert response.json()["scores"] == [0.12, 0.91]
    assert http.calls[0]["json"]["parameters"]["top_n"] == 2


def test_embed_image_uses_data_uri_and_rejects_paths_outside_root(tmp_path):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"fake-png")
    http = _HTTP([{"output": {"embeddings": [{"index": 0, "embedding": [1.0, 0.0]}]}}])
    app = create_app(_settings(tmp_path), http)
    with TestClient(app) as client:
        ok = client.post("/embed_image", json={"image_paths": [str(image)]})
        denied = client.post("/embed_image", json={"image_paths": ["/etc/hosts"]})

    assert ok.status_code == 200
    assert math.isclose(ok.json()["vectors"][0][0], 1.0)
    encoded = http.calls[0]["json"]["input"]["contents"][0]["image"]
    assert encoded.startswith("data:image/png;base64,")
    assert denied.status_code == 400
    assert "CLOUD_IMAGE_ROOT" in denied.json()["detail"]
