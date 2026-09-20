"""API key 令牌桶：鉴权后限流、身份隔离、重填及隐私边界。"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from pharos.identity import Identity
from pharos.rate_limit import KeyRateLimiter
from tests._fakes import FakeRetriever, make_app, make_cfg


def test_token_bucket_refills_and_never_keeps_raw_key():
    now = [100.0]
    limiter = KeyRateLimiter(2.0, 2, clock=lambda: now[0])
    assert limiter.allow("secret-key") == (True, 0)
    assert limiter.allow("secret-key") == (True, 0)
    assert limiter.allow("secret-key") == (False, 1)
    assert "secret-key" not in limiter._buckets
    now[0] += 0.5
    assert limiter.allow("secret-key") == (True, 0)
    assert limiter.allow("other-key") == (True, 0)


def test_authenticated_keys_have_independent_buckets_and_probes_are_exempt():
    keys = {
        "a" * 20: Identity(name="alice", tenant="t1"),
        "b" * 20: Identity(name="bob", tenant="t1"),
    }
    retriever = FakeRetriever()
    retriever.store.client = SimpleNamespace(collection_exists=lambda name: True)
    app = make_app(cfg=make_cfg(rate_limit_rps=0.1, rate_limit_burst=1), keys=keys,
                   retriever=retriever)
    with TestClient(app) as client:
        assert client.get("/v1/me").status_code == 401
        assert client.get("/v1/me", headers={"X-API-Key": "wrong"}).status_code == 401
        first = client.get("/v1/me", headers={"X-API-Key": "a" * 20})
        blocked = client.get("/v1/me", headers={"X-API-Key": "a" * 20})
        other = client.get("/v1/me", headers={"X-API-Key": "b" * 20})
        health = client.get("/healthz")
        ready = client.get("/readyz")
    assert first.status_code == 200 and other.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json()["status"] == "rate_limited"
    assert blocked.json()["retriable"] is True
    assert blocked.json()["retry_after"] >= 1
    assert blocked.headers["Retry-After"] == str(blocked.json()["retry_after"])
    assert health.status_code == 200 and ready.status_code == 200


def test_legacy_key_is_rate_limited_after_authentication():
    app = make_app(cfg=make_cfg(api_key="legacy-secret", rate_limit_rps=0.1,
                                rate_limit_burst=1))
    with TestClient(app) as client:
        assert client.get("/v1/me", headers={"X-API-Key": "legacy-secret"}).status_code == 200
        assert client.get("/v1/me", headers={"X-API-Key": "legacy-secret"}).status_code == 429
        assert client.get("/v1/me", headers={"X-API-Key": "wrong"}).status_code == 401


def test_limit_disabled_by_default_and_invalid_config_rejected():
    app = make_app(cfg=make_cfg(api_key="legacy"))
    with TestClient(app) as client:
        for _ in range(12):
            assert client.get("/v1/me", headers={"X-API-Key": "legacy"}).status_code == 200
    try:
        make_app(cfg=make_cfg(api_key="legacy", rate_limit_rps=-1))
    except SystemExit:
        pass
    else:
        raise AssertionError("负速率必须拒绝启动")
