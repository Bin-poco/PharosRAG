"""Run reproducible smoke checks against the production /v1/ask API.

This is deliberately not a semantic benchmark. It verifies stable production
contracts around routing, bounded agent execution, citation provenance and
grounded refusal while allowing the model to vary its wording.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx


HERE = Path(__file__).resolve().parent
DEFAULT_SUITE = HERE / "official_agent_smoke.json"
_REFUSAL = re.compile(
    r"信息不足|没有足够|无法回答|无法得出|未提供|没有提供|没有相关|没有找到|查不到|找不到"
    r"|don'?t have enough|not contain|no (?:relevant )?information|unable to answer|cannot answer",
    re.I,
)


def load_suite(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError("suite 必须是含 cases 数组的 JSON 对象")
    seen: set[str] = set()
    for index, case in enumerate(data["cases"], 1):
        if not isinstance(case, dict):
            raise ValueError(f"cases[{index}] 必须是对象")
        case_id = str(case.get("id") or "").strip()
        if not case_id or case_id in seen:
            raise ValueError(f"cases[{index}] id 为空或重复:{case_id!r}")
        seen.add(case_id)
        if case.get("mode") not in {"direct", "agent", "auto"}:
            raise ValueError(f"{case_id}:mode 必须 direct|agent|auto")
        if not str(case.get("query") or "").strip():
            raise ValueError(f"{case_id}:query 为空")
        if not isinstance(case.get("expect"), dict):
            raise ValueError(f"{case_id}:expect 必须是对象")
    return data


def check_response(case: dict[str, Any], data: dict[str, Any]) -> list[str]:
    """Return contract violations; an empty list means the case passed."""
    errors: list[str] = []
    expect = case["expect"]
    if data.get("status") != "ok":
        return [f"status={data.get('status')!r}: {data.get('hint', '')}"]

    answer = str(data.get("answer") or "")
    citations = data.get("citations") or []
    citation_docs = {str(item.get("doc_id")) for item in citations if isinstance(item, dict)}
    # 冒烟检查的是“整题硬拒答”。有引用的答案可能诚实声明某个次要细节未提供，不能因此把整份
    # 有依据的回答判成拒答；部分回答质量属于 golden-answer benchmark 的职责。
    is_refusal = bool(_REFUSAL.search(answer)) and not citations

    if bool(expect.get("refusal")) != is_refusal:
        errors.append(f"refusal 期望 {bool(expect.get('refusal'))}，实际 {is_refusal}")
    if len(citations) < int(expect.get("min_citations", 0)):
        errors.append(f"引用数 {len(citations)} < {expect['min_citations']}")
    if "max_citations" in expect and len(citations) > int(expect["max_citations"]):
        errors.append(f"引用数 {len(citations)} > {expect['max_citations']}")

    allowed_docs = set(case.get("doc_ids") or [])
    outside = citation_docs - allowed_docs
    if outside:
        errors.append(f"引用越出指定文档范围:{sorted(outside)}")
    min_docs = int(expect.get("min_citation_docs", 0))
    if len(citation_docs) < min_docs:
        errors.append(f"不同引用文档数 {len(citation_docs)} < {min_docs}")
    for group in expect.get("citation_doc_groups") or []:
        if citation_docs.isdisjoint(group):
            errors.append(f"缺少引用组中任一文档:{group}")

    expected_mode = expect.get("selected_mode")
    if expected_mode and (data.get("route") or {}).get("selected_mode") != expected_mode:
        actual = (data.get("route") or {}).get("selected_mode")
        errors.append(f"selected_mode 期望 {expected_mode}，实际 {actual}")

    budget = data.get("budget") or {}
    retrievals = int(budget.get("retrievals") or 0)
    if retrievals < int(expect.get("min_retrievals", 0)):
        errors.append(f"检索轮数 {retrievals} < {expect['min_retrievals']}")
    if "max_retrievals" in expect and retrievals > int(expect["max_retrievals"]):
        errors.append(f"检索轮数 {retrievals} > {expect['max_retrievals']}")
    limits = budget.get("limits") or {}
    for field, limit_field in (("retrievals", "max_retrievals"),
                               ("llm_calls", "max_llm_calls"),
                               ("steps", "max_steps")):
        if field in budget and limit_field in limits and budget[field] > limits[limit_field]:
            errors.append(f"预算越界:{field}={budget[field]} > {limits[limit_field]}")

    trace_actions = {step.get("action") for step in (data.get("trace") or [])
                     if isinstance(step, dict)}
    for action in expect.get("trace_actions") or []:
        if action not in trace_actions:
            errors.append(f"trace 缺少 action={action}")

    if not is_refusal and data.get("finish_reason") == "length":
        errors.append("答案被 max_tokens 截断(finish_reason=length)")
    return errors


def _select_cases(suite: dict[str, Any], *, profile: str,
                  selected_ids: list[str]) -> list[dict[str, Any]]:
    cases = suite["cases"]
    if selected_ids:
        wanted = set(selected_ids)
        selected = [case for case in cases if case["id"] in wanted]
        missing = wanted - {case["id"] for case in selected}
        if missing:
            raise ValueError(f"未知 case id:{sorted(missing)}")
        return selected
    if profile == "quick":
        return [case for case in cases if "quick" in (case.get("tags") or [])]
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="检查真实 /v1/ask 的路由、引用、预算与拒答契约")
    parser.add_argument("--suite", default=str(DEFAULT_SUITE))
    parser.add_argument("--profile", choices=["quick", "all"], default="quick")
    parser.add_argument("--case", action="append", default=[], dest="case_ids",
                        help="只运行指定 case id；可重复")
    parser.add_argument("--url", default=os.environ.get("PHAROS_URL", "http://127.0.0.1:8787"))
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--json-out", help="可选：保存本次逐例结果")
    args = parser.parse_args()

    try:
        suite = load_suite(args.suite)
        cases = _select_cases(suite, profile=args.profile, selected_ids=args.case_ids)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"用例文件无效:{exc}", file=sys.stderr)
        return 2

    api_key = os.environ.get("PHAROS_API_KEY") or os.environ.get("PHAROS_DEV_API_KEY")
    if not api_key:
        print("缺 API key：先 source .env.mac，或设置 PHAROS_API_KEY。", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    passed = 0
    headers = {"X-API-Key": api_key}
    with httpx.Client(base_url=args.url.rstrip("/"), headers=headers,
                      timeout=httpx.Timeout(args.timeout, connect=5.0)) as client:
        for index, case in enumerate(cases, 1):
            payload = {key: case[key] for key in
                       ("query", "mode", "top_k", "rerank", "doc_ids", "doc_type", "kind", "strategy")
                       if key in case}
            try:
                response = client.post("/v1/ask", json=payload)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("响应不是 JSON 对象")
                errors = check_response(case, data)
            except Exception as exc:
                data = {}
                errors = [f"请求失败:{type(exc).__name__}:{exc}"]

            ok = not errors
            passed += int(ok)
            budget = data.get("budget") or {}
            route = (data.get("route") or {}).get("selected_mode", case["mode"])
            mark = "PASS" if ok else "FAIL"
            print(f"[{index:02d}/{len(cases):02d}] {mark} {case['id']} "
                  f"route={route} retrievals={budget.get('retrievals', '-')} "
                  f"llm={budget.get('llm_calls', '-')} citations={len(data.get('citations') or [])}",
                  flush=True)
            for error in errors:
                print(f"         - {error}", flush=True)
            rows.append({
                "id": case["id"], "passed": ok, "errors": errors,
                "status": data.get("status"), "route": route,
                "retrievals": budget.get("retrievals"), "llm_calls": budget.get("llm_calls"),
                "citation_doc_ids": sorted({c.get("doc_id") for c in (data.get("citations") or [])
                                             if isinstance(c, dict) and c.get("doc_id")}),
                "finish_reason": data.get("finish_reason"),
            })

    report = {"suite_version": suite.get("version"), "profile": args.profile,
              "base_url": args.url, "passed": passed, "total": len(cases), "rows": rows}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    print(f"\n结果: {passed}/{len(cases)} 通过")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
