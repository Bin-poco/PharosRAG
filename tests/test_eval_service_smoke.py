from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("service_smoke", ROOT / "eval" / "service_smoke.py")
assert SPEC and SPEC.loader
service_smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service_smoke)


def test_official_agent_smoke_suite_is_valid_and_balanced():
    suite = service_smoke.load_suite(ROOT / "eval" / "official_agent_smoke.json")
    cases = suite["cases"]

    assert len(cases) == 10
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["mode"] for case in cases} == {"direct", "agent", "auto"}
    assert len([case for case in cases if "quick" in case["tags"]]) == 4
    assert any(case["expect"].get("refusal") for case in cases)
    assert all(case.get("doc_ids") for case in cases)


def test_check_response_accepts_bounded_grounded_agent_result():
    case = {
        "doc_ids": ["doc_a", "doc_b"],
        "expect": {
            "selected_mode": "agent",
            "refusal": False,
            "min_citations": 2,
            "min_citation_docs": 2,
            "min_retrievals": 1,
            "trace_actions": ["grade"],
            "citation_doc_groups": [["doc_a"], ["doc_b"]],
        },
    }
    data = {
        "status": "ok",
        "answer": "grounded answer",
        "citations": [{"doc_id": "doc_a"}, {"doc_id": "doc_b"}],
        "route": {"selected_mode": "agent"},
        "trace": [{"action": "grade"}],
        "budget": {
            "retrievals": 2, "llm_calls": 3, "steps": 7,
            "limits": {"max_retrievals": 3, "max_llm_calls": 4, "max_steps": 10},
        },
        "finish_reason": "stop",
    }

    assert service_smoke.check_response(case, data) == []


def test_check_response_reports_provenance_route_budget_and_truncation_failures():
    case = {
        "doc_ids": ["doc_a"],
        "expect": {
            "selected_mode": "agent", "refusal": False, "min_citations": 1,
            "min_retrievals": 1, "trace_actions": ["grade"],
            "citation_doc_groups": [["doc_a"]],
        },
    }
    data = {
        "status": "ok", "answer": "answer", "citations": [{"doc_id": "outside"}],
        "route": {"selected_mode": "direct"}, "trace": [],
        "budget": {"retrievals": 4, "llm_calls": 1, "steps": 1,
                   "limits": {"max_retrievals": 3, "max_llm_calls": 4, "max_steps": 10}},
        "finish_reason": "length",
    }

    errors = service_smoke.check_response(case, data)
    assert any("引用越出" in error for error in errors)
    assert any("缺少引用组" in error for error in errors)
    assert any("selected_mode" in error for error in errors)
    assert any("预算越界" in error for error in errors)
    assert any("截断" in error for error in errors)


def test_check_response_accepts_grounded_refusal_without_citations():
    case = {
        "doc_ids": ["missing"],
        "expect": {"selected_mode": "agent", "refusal": True,
                   "min_citations": 0, "max_citations": 0, "min_retrievals": 1},
    }
    data = {
        "status": "ok",
        "answer": "I don't have enough information in the provided context to answer.",
        "citations": [],
        "route": {"selected_mode": "agent"},
        "trace": [{"action": "retrieve"}],
        "budget": {"retrievals": 1, "llm_calls": 1, "steps": 3,
                   "limits": {"max_retrievals": 3, "max_llm_calls": 4, "max_steps": 10}},
        "finish_reason": None,
    }

    assert service_smoke.check_response(case, data) == []


def test_check_response_does_not_treat_cited_partial_caveat_as_hard_refusal():
    case = {
        "doc_ids": ["doc_a"],
        "expect": {"refusal": False, "min_citations": 1},
    }
    data = {
        "status": "ok",
        "answer": "核心结论有依据 [cite:1]；文档未提供一个次要边界条件。",
        "citations": [{"doc_id": "doc_a"}],
        "finish_reason": "stop",
    }

    assert service_smoke.check_response(case, data) == []
