from __future__ import annotations

import importlib.util
import os
from collections import Counter
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agent_benchmark", ROOT / "eval" / "agent_benchmark.py")
assert SPEC and SPEC.loader
agent_benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_benchmark)


def _positive_case():
    return {
        "id": "positive",
        "category": "cross_doc",
        "query": "q",
        "doc_ids": ["doc_a", "doc_b"],
        "gold": {
            "reference_answer": "answer",
            "required_facts": [
                {"id": "a", "description": "fact a"},
                {"id": "b", "description": "fact b"},
            ],
            "citation_doc_groups": [["doc_a"], ["doc_b"]],
            "should_refuse": False,
        },
    }


def _response(*, docs=("doc_a", "doc_b"), answer="grounded", citations=True):
    return {
        "status": "ok",
        "answer": answer,
        "citations": ([{"marker": index, "doc_id": doc, "text": f"evidence {doc}"}
                       for index, doc in enumerate(docs, 1)] if citations else []),
        "finish_reason": "stop",
        "route": {"selected_mode": "agent"},
        "budget": {
            "retrievals": 2, "llm_calls": 3, "steps": 5,
            "limits": {"max_retrievals": 3, "max_llm_calls": 4, "max_steps": 8},
        },
    }


def test_official_gold_is_valid_balanced_and_references_manifest():
    suite = agent_benchmark.load_suite()
    cases = suite["cases"]

    assert len(cases) == 26
    assert suite["provenance"]["human_review"] == "pending"
    assert Counter(case["category"] for case in cases) == {
        "single": 5, "multi_section": 7, "cross_doc": 9, "no_answer": 5,
    }
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case["doc_ids"] for case in cases)
    assert all(case["gold"]["required_facts"] for case in cases
               if case["category"] != "no_answer")
    assert all(not case["gold"]["required_facts"] for case in cases
               if case["category"] == "no_answer")
    agent_benchmark.validate_corpus_scope(suite, agent_benchmark.manifest_doc_ids())


def test_official_gold_v2_preserves_v1_and_covers_reviewed_boundaries():
    v1 = agent_benchmark.load_suite()
    v2 = agent_benchmark.load_suite(ROOT / "eval" / "official_agent_gold_v2.json")
    cases = v2["cases"]
    by_id = {case["id"]: case for case in cases}

    assert v1["version"] == 1 and v2["version"] == 2
    assert len(cases) == 32
    assert [case["id"] for case in cases[:26]] == [case["id"] for case in v1["cases"]]
    assert Counter(case["category"] for case in cases) == {
        "single": 9, "multi_section": 6, "cross_doc": 12, "no_answer": 5,
    }
    assert v2["provenance"]["human_review"] == "pending"
    assert v2["provenance"]["ai_source_review"]["status"] == "completed_2026-09-19"
    assert len(by_id) == len(cases)
    assert all(case["gold"]["required_facts"] for case in cases
               if case["category"] != "no_answer")
    assert all(not case["gold"]["should_refuse"] for case in cases[26:])
    assert by_id["multi_qdrant_storage"]["category"] == "cross_doc"
    assert by_id["cross_fastapi_background_celery"]["gold"]["citation_doc_groups"] == [
        ["fastapi__background_tasks"], ["celery__first_steps"], ["celery__tasks"],
    ]
    assert by_id["cross_docker_networking"]["gold"]["citation_doc_groups"] == [
        ["docker__compose_networking"], ["docker__bridge_network"],
        ["docker__port_publishing"],
    ]
    agent_benchmark.validate_corpus_scope(v2, agent_benchmark.manifest_doc_ids())


def test_official_gold_v2_local_sources_exist():
    corpus_dir = os.environ.get("PHAROS_TEST_CORPUS_DIR")
    if not corpus_dir:
        pytest.skip("设置 PHAROS_TEST_CORPUS_DIR 后检查本地下载的官方语料")
    source_root = Path(corpus_dir).expanduser()
    assert source_root.is_dir(), f"语料目录不存在: {source_root}"
    v2 = agent_benchmark.load_suite(ROOT / "eval" / "official_agent_gold_v2.json")
    doc_ids = {doc_id for case in v2["cases"] for doc_id in case["doc_ids"]}
    missing = [doc_id for doc_id in sorted(doc_ids)
               if not any((source_root / doc_id / name).is_file()
                          for name in ("source.md", "source.rst"))]
    assert not missing, f"评测语料缺少源文件: {missing}"


def test_check_response_accepts_complete_grounded_result():
    result = agent_benchmark.check_response(_positive_case(), _response())

    assert result["passed"]
    assert result["citation_group_recall"] == 1.0
    assert result["citation_doc_ids"] == ["doc_a", "doc_b"]


def test_check_response_reports_missing_source_scope_and_budget():
    data = _response(docs=("doc_a", "doc_x"))
    data["finish_reason"] = "length"
    data["budget"]["retrievals"] = 4

    result = agent_benchmark.check_response(_positive_case(), data)

    assert not result["passed"]
    assert result["citation_group_recall"] == 0.5
    assert any("引用越出" in error for error in result["errors"])
    assert any("缺少引用组" in error for error in result["errors"])
    assert any("预算越界" in error for error in result["errors"])
    assert any("截断" in error for error in result["errors"])


def test_no_answer_requires_clear_refusal_but_may_cite_checked_scope():
    case = {
        "id": "negative", "category": "no_answer", "query": "secret",
        "doc_ids": ["doc_a"],
        "gold": {"reference_answer": "not present", "required_facts": [],
                 "citation_doc_groups": [], "should_refuse": True},
    }
    accepted = agent_benchmark.check_response(
        case, _response(docs=(), answer="指定文档没有提供该信息，无法确定。", citations=False))
    invented = agent_benchmark.check_response(
        case, _response(docs=(), answer="负责人是张三，电话 123。", citations=False))
    cited = agent_benchmark.check_response(
        case, _response(docs=("doc_a",), answer="文档没有提供该信息。"))

    assert accepted["passed"] and accepted["hard_refusal"]
    assert not invented["passed"]
    assert cited["passed"] and not cited["hard_refusal"]


def test_validate_judgement_rejects_unknown_fact_ids():
    case = _positive_case()
    valid = agent_benchmark.validate_judgement(case, {
        "faithful": True, "correct": True, "covered_fact_ids": ["a", "b", "a"],
        "unsupported_claims": [], "reason": "ok",
    })
    assert valid["covered_fact_ids"] == ["a", "b"]

    with pytest.raises(ValueError, match="未知 fact id"):
        agent_benchmark.validate_judgement(case, {
            "faithful": True, "correct": True, "covered_fact_ids": ["c"],
            "unsupported_claims": [], "reason": "bad",
        })


def test_summary_uses_paired_direct_delta_and_markdown_warns_about_metrics():
    base = {
        "case_id": "x", "category": "cross_doc", "should_refuse": False,
        "required_fact_count": 2, "contract_passed": True,
        "citation_group_recall": 0.5, "refusal_text": False, "hard_refusal": False,
        "latency_ms": 100.0, "retrievals": None, "llm_calls": None,
        "selected_mode": "direct", "degraded": False,
        "judge": {"correct": False, "faithful": True, "covered_fact_ids": ["a"]},
    }
    other = {
        **base, "mode": "agent", "selected_mode": "agent", "latency_ms": 250.0,
        "citation_group_recall": 1.0,
        "judge": {"correct": True, "faithful": True, "covered_fact_ids": ["a", "b"]},
    }
    base["mode"] = "direct"
    summary = agent_benchmark.summarize_rows([base, other])
    pair = summary["paired_vs_direct"][0]

    assert pair["mode"] == "agent"
    assert pair["citation_group_recall_delta"] == 0.5
    assert pair["correctness_delta"] == 1.0
    assert pair["latency_ms_delta"] == 150.0

    report = {
        "created_at": "now", "corpus": "test", "case_count": 1,
        "run_count": 2, "modes": ["direct", "agent"], "judge": "deepseek",
        "summary": summary,
        "rows": [
            {**base, "contract_errors": []},
            {**other, "contract_errors": []},
        ],
    }
    markdown = agent_benchmark.render_markdown(report)
    assert "相对 direct 的配对变化" in markdown
    assert "引用组召回只说明" in markdown
