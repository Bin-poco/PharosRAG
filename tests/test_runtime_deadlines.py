"""Deadline tests use no network, real models or production data."""
from copy import deepcopy
from threading import Event
import time
from types import SimpleNamespace

import pytest

from embedder.config import EmbedConfig
from embedder.remote import _post_retry
from generator.llm import OpenAICompatibleLLM
from pharos.agentic import AgentLimits
from rag_runtime.deadline import Deadline, DeadlineExceeded, remaining_seconds
from tests._fakes import make_user
from tests.test_agentic import _runner, _row


@pytest.mark.parametrize("stage", ["retrieve", "controller", "answer"])
def test_agent_returns_on_deadline_and_drops_late_results(stage):
    runner, retriever, llm = _runner(
        {"q": [_row("c1", "evidence")]},
        ['{"sufficient":true,"reason_code":"complete"}'],
        limits=AgentLimits(timeout_seconds=0.1))
    entered, release, completed = Event(), Event(), Event()
    target, name = ((runner.generator, "retrieve") if stage == "retrieve" else
                    (runner.controller, "assess") if stage == "controller" else
                    (runner.generator, "answer_from_contexts"))
    original = getattr(target, name)

    def delayed(*args, **kwargs):
        entered.set()
        try:
            release.wait(2)
            return original(*args, **kwargs)
        finally:
            completed.set()

    setattr(target, name, delayed)
    started = time.monotonic()
    try:
        run = runner.run("q", make_user(), mode="agent" if stage == "controller" else "auto")
        assert entered.is_set()
        assert time.monotonic() - started < 1.0  # Must not wait for the 2s blocking call.
        assert run.degraded and run.answer.citations == []
        assert run.trace[-1]["reason"] == "timeout"
        before = deepcopy(run.trace)
    finally:
        release.set()
        assert completed.wait(1)
    assert run.trace == before
    if stage != "answer":
        assert llm.answer_calls == 0, "no generation after an expired retrieval/controller"
    assert len(retriever.calls) <= 1


def test_deadline_context_is_not_leaked_to_next_request():
    first = Deadline(1)
    assert 0 < first.call(remaining_seconds) <= 1
    assert remaining_seconds() is None
    second = Deadline(2)
    assert 1 < second.call(remaining_seconds) <= 2


def test_remote_retries_and_backoff_share_remaining_budget():
    calls = []

    class Client:
        def post(self, path, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status_code=503)

    cfg = EmbedConfig(inference_retries=5, inference_backoff=5)
    with pytest.raises(DeadlineExceeded):
        Deadline(0.1).call(lambda: _post_retry(Client(), cfg, "/embed", {}))
    assert len(calls) == 1
    assert 0 < calls[0]["timeout"].read <= 0.1


def test_llm_uses_remaining_timeout_without_sdk_retries():
    options = []
    llm = object.__new__(OpenAICompatibleLLM)
    llm.timeout, llm.model, llm.max_tokens, llm.temperature = 120, "test", 20, 0
    llm.send_thinking = False
    response = SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(content="answer"))])

    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))

        def with_options(self, **kwargs):
            options.append(kwargs)
            return self

    llm._client = Client()
    assert Deadline(1).call(lambda: llm.complete([])) == "answer"
    assert options[0]["max_retries"] == 0
    assert 0 < options[0]["timeout"] <= 1


def test_saturated_execution_pool_does_not_queue_unbounded_work(monkeypatch):
    import rag_runtime.deadline as module
    from threading import BoundedSemaphore
    slots = BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(module, "_SLOTS", slots)
    calls = []
    try:
        with pytest.raises(DeadlineExceeded):
            Deadline(0.01).call(lambda: calls.append("must not start"))
    finally:
        slots.release()
    assert not calls
