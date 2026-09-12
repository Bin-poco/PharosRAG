"""Agentic RAG 状态机测试：路由、多轮补检、ACL、预算与服务接口。"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from generator.generate import Generator
from pharos.agentic import AgentLimits, AgentRun, AgenticRunner, requires_agent
from tests._fakes import FakeRetriever, make_app, make_cfg, make_hit, make_res, make_user


def _row(cid: str, text: str, *, acl=None):
    extra = {}
    if acl is not None:
        extra["acl"] = acl
    return make_res(make_hit(cid=cid, doc=f"doc-{cid}", text=text, **extra), ctx_text=text)


class _ScriptedLLM:
    def __init__(self, controller_outputs, answer="最终答案 [cite:1]"):
        self.controller_outputs = list(controller_outputs)
        self.answer = answer
        self.controller_payloads = []
        self.answer_calls = 0
        self.last_finish_reason = "stop"

    def complete(self, messages):
        if "evidence controller" in messages[0].content:
            self.controller_payloads.append(json.loads(messages[1].content))
            output = self.controller_outputs.pop(0)
            if isinstance(output, Exception):
                raise output
            return output
        self.answer_calls += 1
        return self.answer


class _QueryRetriever:
    def __init__(self, rows_by_query):
        self.rows_by_query = rows_by_query
        self.calls = []

    def search_with_context(self, query, user, top_k=None, rerank=False, **kwargs):
        self.calls.append({"query": query, "tenant": user.tenant, **kwargs})
        return list(self.rows_by_query.get(query, []))


def _runner(rows_by_query, decisions, *, answer="最终答案 [cite:1]", limits=None,
            acl_check=None):
    retriever = _QueryRetriever(rows_by_query)
    llm = _ScriptedLLM(decisions, answer=answer)
    generator = Generator(retriever, llm, acl_check=acl_check)
    return AgenticRunner(generator, limits=limits), retriever, llm


def test_complexity_router_is_conservative():
    assert not requires_agent("Docker volume 和 bind mount 有什么区别？")
    assert requires_agent("结合开发和生产环境，设计一套 Docker 数据持久化方案")


def test_auto_simple_query_stays_direct():
    runner, retriever, llm = _runner({"简单问题": [_row("c1", "证据")]}, [])
    run = runner.run("简单问题", make_user(), mode="auto")
    assert run.selected_mode == "direct"
    assert run.retrievals == 1 and run.llm_calls == 1
    assert llm.controller_payloads == []
    assert [step["action"] for step in run.trace] == ["retrieve", "route", "answer"]
    assert retriever.calls[0]["tenant"] == "t1"


def test_forced_agent_rewrites_and_merges_evidence():
    decisions = [
        '{"sufficient":false,"reason_code":"missing_prod","missing":["生产环境"],'
        '"next_queries":["生产环境 Docker 持久化"]}',
        '{"sufficient":true,"reason_code":"complete","missing":[],"next_queries":[]}',
    ]
    runner, retriever, llm = _runner(
        {"设计方案": [_row("c1", "开发环境使用 bind mount")],
         "生产环境 Docker 持久化": [_row("c2", "生产环境使用 named volume")]},
        decisions, answer="开发用 bind mount [cite:1]，生产用 volume [cite:2]",
    )
    run = runner.run("设计方案", make_user(), mode="agent", strategy="hybrid")
    assert run.selected_mode == "agent" and not run.degraded
    assert run.retrievals == 2 and run.llm_calls == 3
    assert [c.marker for c in run.answer.citations] == [1, 2]
    assert [call["query"] for call in retriever.calls] == ["设计方案", "生产环境 Docker 持久化"]
    assert [s["action"] for s in run.trace] == ["route", "retrieve", "grade", "retrieve", "grade", "answer"]


def test_controller_failure_degrades_to_direct_generation():
    runner, _, llm = _runner({"q": [_row("c1", "证据")]}, [RuntimeError("secret URL")])
    run = runner.run("q", make_user(), mode="agent")
    assert run.degraded and run.answer.text.startswith("最终答案")
    fallback = next(s for s in run.trace if s["action"] == "fallback")
    assert fallback["reason"] == "controller_unavailable"
    assert "secret URL" not in str(run.trace)
    assert llm.answer_calls == 1


def test_acl_filters_controller_and_final_prompt():
    rows = [_row("public", "PUBLIC", acl={"visibility": "public"}),
            _row("secret", "TOP SECRET", acl={"visibility": "private"})]
    decision = '{"sufficient":true,"reason_code":"ok","missing":[],"next_queries":[]}'
    runner, _, llm = _runner(
        {"q": rows}, [decision],
        acl_check=lambda acl, _user: acl.get("visibility") == "public",
    )
    run = runner.run("q", make_user(), mode="agent")
    assert run.answer.n_contexts == 1
    assert "PUBLIC" in str(llm.controller_payloads)
    assert "TOP SECRET" not in str(llm.controller_payloads)
    assert "TOP SECRET" not in run.answer.raw_messages[1].content


def test_retrieval_budget_stops_loop():
    decision = ('{"sufficient":false,"reason_code":"missing","missing":["x"],'
                '"next_queries":["next"]}')
    limits = AgentLimits(max_retrievals=1, max_llm_calls=4, max_steps=10)
    runner, retriever, _ = _runner({"q": [_row("c1", "证据")]}, [decision], limits=limits)
    run = runner.run("q", make_user(), mode="agent")
    assert run.retrievals == 1 and len(retriever.calls) == 1
    assert run.answer.n_contexts == 0
    assert run.trace[-1] == {"step": 4, "action": "stop", "reason": "retrieval_budget_exhausted"}


def test_service_agent_modes_and_explicit_endpoint():
    answer = Generator(FakeRetriever(), _ScriptedLLM([])).answer_from_contexts("q", [], [])

    class _FakeRunner:
        generator = None

        def run(self, query, user, *, mode, **kwargs):
            return AgentRun(answer=answer, requested_mode=mode, selected_mode="agent",
                            route_reasons=["test"], trace=[{"step": 1, "action": "route"}],
                            retrievals=1, llm_calls=1, elapsed_ms=2.5,
                            limits=AgentLimits(), degraded=False)

    def agent_factory(generator, cfg):
        runner = _FakeRunner()
        runner.generator = generator
        return runner

    # agent_factory 会在 generator 之后构建，因此提供一个不访问网络的 generator。
    def generator_factory(retriever, cfg):
        return Generator(retriever, _ScriptedLLM([]))

    app = make_app(cfg=make_cfg(), generator_factory=generator_factory,
                   agent_factory=agent_factory)
    with TestClient(app) as client:
        auto = client.post("/v1/ask", json={"query": "q", "mode": "auto"}).json()
        forced = client.post("/v1/agent/ask", json={"query": "q", "mode": "direct"}).json()
        bad = client.post("/v1/ask", json={"query": "q", "mode": "magic"}).json()
    assert auto["route"]["requested_mode"] == "auto"
    assert forced["route"]["requested_mode"] == "agent"
    assert bad["status"] == "bad_arg"
