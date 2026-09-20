"""Agentic RAG 状态机测试：路由、多轮补检、ACL、预算与服务接口。"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from generator.generate import Generator
from pharos.agentic import (
    AgentLimits,
    AgentRun,
    AgenticRunner,
    EvidenceController,
    requires_agent,
)
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


def test_answer_continuation_counts_against_agent_llm_budget():
    class _LengthThenStopLLM:
        def __init__(self):
            self.calls = 0
            self.last_finish_reason = None

        def complete(self, messages):
            self.calls += 1
            self.last_finish_reason = "length" if self.calls == 1 else "stop"
            return "前半 [cite:1]" if self.calls == 1 else "后半 [cite:1]"

    retriever = _QueryRetriever({"简单问题": [_row("c1", "证据")]})
    llm = _LengthThenStopLLM()
    generator = Generator(retriever, llm, max_continuations=1)
    runner = AgenticRunner(generator, limits=AgentLimits(max_llm_calls=2))
    run = runner.run("简单问题", make_user(), mode="auto")
    assert run.llm_calls == 2 and llm.calls == 2
    assert run.answer.continuations == 1 and run.answer.finish_reason == "stop"
    assert run.trace[-1]["continuations"] == 1


def test_answer_continuation_cannot_exceed_agent_llm_budget():
    class _AlwaysLengthLLM:
        def __init__(self):
            self.calls = 0
            self.last_finish_reason = "length"

        def complete(self, messages):
            self.calls += 1
            return "部分答案 [cite:1]"

    retriever = _QueryRetriever({"简单问题": [_row("c1", "证据")]})
    llm = _AlwaysLengthLLM()
    generator = Generator(retriever, llm, max_continuations=2)
    runner = AgenticRunner(generator, limits=AgentLimits(max_llm_calls=1))
    run = runner.run("简单问题", make_user(), mode="auto")
    assert run.llm_calls == 1 and llm.calls == 1
    assert run.answer.finish_reason == "length" and run.answer.continuations == 0


def test_auto_zero_recall_escalates_and_recovers():
    decisions = [
        '{"sufficient":false,"reason_code":"no_evidence","missing":["Docker evidence"],'
        '"next_queries":["Docker volume persistence"]}',
        '{"sufficient":true,"reason_code":"complete","missing":[],"next_queries":[]}',
    ]
    runner, retriever, _ = _runner(
        {"unknown wording": [], "Docker volume persistence": [_row("c1", "volume persists data")]},
        decisions,
    )
    run = runner.run("unknown wording", make_user(), mode="auto")
    assert run.selected_mode == "agent"
    assert run.route_reasons == ["zero_recall"]
    assert [call["query"] for call in retriever.calls] == ["unknown wording", "Docker volume persistence"]
    assert run.retrievals == 2 and run.llm_calls == 3


def test_auto_direct_refusal_escalates_to_agent():
    refusal = "I don't have enough information in the provided context to answer."
    decision = '{"sufficient":true,"reason_code":"complete","missing":[],"next_queries":[]}'
    runner, _, _ = _runner({"q": [_row("c1", "evidence")]}, [decision], answer=refusal)
    run = runner.run("q", make_user(), mode="auto")
    assert run.selected_mode == "agent"
    assert run.route_reasons == ["simple_query_with_evidence", "direct_refusal_escalation"]
    assert [step["action"] for step in run.trace] == ["retrieve", "route", "answer", "route", "grade", "answer"]
    assert run.llm_calls == 3


def test_forced_agent_rewrites_and_merges_evidence():
    decisions = [
        '{"sufficient":false,"reason_code":"missing_prod","missing":["生产环境"],'
        '"next_queries":["生产环境 Docker 持久化"]}',
        '{"sufficient":true,"reason_code":"complete","missing":[],"next_queries":[]}',
    ]
    runner, retriever, llm = _runner(
        {"设计方案": [_row("c1", "开发环境使用 bind mount")],
         "生产环境 Docker 持久化": [
             _row("c1", "开发环境使用 bind mount"),
             _row("c2", "生产环境使用 named volume"),
         ]},
        decisions, answer="开发用 bind mount [cite:1]，生产用 volume [cite:2]",
    )
    run = runner.run("设计方案", make_user(), mode="agent", strategy="hybrid")
    assert run.selected_mode == "agent" and not run.degraded
    assert run.retrievals == 2 and run.llm_calls == 3
    assert run.evidence_chunk_ids == ["c1", "c2"]
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


def test_invalid_controller_json_degrades_without_leaking_raw_output():
    runner, _, _ = _runner({"q": [_row("c1", "证据")]}, ["not-json secret payload"])
    run = runner.run("q", make_user(), mode="agent")
    assert run.degraded
    fallback = next(step for step in run.trace if step["action"] == "fallback")
    assert fallback["reason"] == "controller_invalid_json"
    assert "secret payload" not in str(run.trace)


def test_controller_budget_preserves_late_focused_hits():
    llm = _ScriptedLLM([
        '{"sufficient":true,"reason_code":"complete","missing":[],"next_queries":[]}'
    ])
    controller = EvidenceController(llm, max_evidence_chars=1200)
    contexts = [
        {"source": "initial", "matched_text": "INITIAL-HIT", "text": "A" * 2000},
        {"source": "retry", "matched_text": "RETRY-HIT", "text": "B" * 2000},
        {"source": "timeout", "matched_text": "TIMEOUT-HIT", "text": "C" * 2000},
    ]
    controller.assess("q", contexts, ["q", "retry query", "timeout query"])
    evidence = llm.controller_payloads[0]["evidence"]
    assert [item["source"] for item in evidence] == ["initial", "retry", "timeout"]
    assert all(marker in item["text"] for marker, item in zip(
        ("INITIAL-HIT", "RETRY-HIT", "TIMEOUT-HIT"), evidence))
    assert sum(len(item["text"]) for item in evidence) <= 1200


def test_controller_finds_query_term_late_in_expanded_section():
    llm = _ScriptedLLM([
        '{"sufficient":true,"reason_code":"complete","missing":[],"next_queries":[]}'
    ])
    controller = EvidenceController(llm, max_evidence_chars=1000)
    matched = "Celery can automatically retry selected exceptions."
    expanded = matched + (" unrelated section text" * 200) + (
        " Task.retry_backoff_max caps exponential retry delay at a configured number of seconds."
    )

    controller.assess(
        "Explain automatic retries",
        [{"source": "Celery Tasks", "matched_text": matched, "text": expanded}],
        ["Explain automatic retries", "Celery retry_backoff retry_backoff_max"],
    )

    evidence = llm.controller_payloads[0]["evidence"][0]["text"]
    assert matched in evidence
    assert "retry_backoff_max" in evidence
    assert len(evidence) <= 1000


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
    assert run.answer.n_contexts == 1
    assert run.trace[-2] == {"step": 4, "action": "fallback",
                             "reason": "retrieval_budget_exhausted",
                             "action_taken": "grounded_generation"}
    assert run.trace[-1]["action"] == "answer"
    assert run.trace[-1]["outcome"] == "best_effort_retrieval_budget_exhausted"


def test_best_effort_generation_requires_two_remaining_trace_steps():
    decision = ('{"sufficient":false,"reason_code":"missing","missing":["x"],'
                '"next_queries":["next"]}')
    # route + retrieve + grade 已占 3 步，只剩 1 步时不能声称将执行 grounded generation。
    limits = AgentLimits(max_retrievals=1, max_llm_calls=4, max_steps=4)
    runner, _, llm = _runner({"q": [_row("c1", "证据")]}, [decision], limits=limits)
    run = runner.run("q", make_user(), mode="agent")
    assert run.trace[-1] == {
        "step": 4, "action": "stop", "reason": "retrieval_budget_exhausted"
    }
    assert run.answer.n_contexts == 0
    assert llm.answer_calls == 0


def test_duplicate_or_empty_next_queries_stop_without_retrieval():
    decision = ('{"sufficient":false,"reason_code":"missing","missing":["x"],'
                '"next_queries":["q"," ","q"]}')
    runner, retriever, _ = _runner({"q": [_row("c1", "证据")]}, [decision])
    run = runner.run("q", make_user(), mode="agent")
    assert run.retrievals == 1 and len(retriever.calls) == 1
    assert run.answer.n_contexts == 1
    assert run.trace[-2]["action"] == "fallback"
    assert run.trace[-2]["reason"] == "no_new_query"
    assert run.trace[-1]["outcome"] == "best_effort_no_new_query"


def test_llm_budget_blocks_final_generation():
    limits = AgentLimits(max_retrievals=2, max_llm_calls=1, max_steps=10)
    decision = '{"sufficient":true,"reason_code":"complete","missing":[],"next_queries":[]}'
    runner, _, llm = _runner({"q": [_row("c1", "证据")]}, [decision], limits=limits)
    run = runner.run("q", make_user(), mode="agent")
    assert run.llm_calls == 1 and llm.answer_calls == 0
    assert run.trace[-1] == {"step": 4, "action": "stop", "reason": "llm_budget_exhausted"}
    assert run.answer.n_contexts == 0


def test_step_and_timeout_limits_prevent_work():
    step_runner, step_retriever, _ = _runner(
        {"q": [_row("c1", "证据")]}, [], limits=AgentLimits(max_steps=1))
    step_run = step_runner.run("q", make_user(), mode="agent")
    assert len(step_run.trace) == 1 and step_run.retrievals == 0
    assert not step_retriever.calls

    timeout_runner, timeout_retriever, _ = _runner(
        {"q": [_row("c1", "证据")]}, [], limits=AgentLimits(timeout_seconds=0))
    timeout_run = timeout_runner.run("q", make_user(), mode="agent")
    assert timeout_run.retrievals == 0 and not timeout_retriever.calls


def test_subquery_limit_runs_at_most_two_focused_searches():
    decisions = [
        '{"sufficient":false,"reason_code":"missing","missing":["a","b","c"],'
        '"next_queries":["qa","qb","qc"]}',
        '{"sufficient":true,"reason_code":"complete","missing":[],"next_queries":[]}',
    ]
    limits = AgentLimits(max_retrievals=3, max_subqueries=2)
    runner, retriever, _ = _runner(
        {"q": [_row("c0", "base")], "qa": [], "qb": [_row("c2", "evidence b")],
         "qc": [_row("c3", "must not be searched")]},
        decisions, limits=limits,
    )
    run = runner.run("q", make_user(), mode="agent")
    assert [call["query"] for call in retriever.calls] == ["q", "qa", "qb"]
    assert "qc" not in [step.get("query") for step in run.trace]
    assert run.retrievals == 3 and run.answer.n_contexts == 2


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
