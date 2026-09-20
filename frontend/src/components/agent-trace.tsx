import { Badge } from "@/components/ui/badge";

export type AgentStep = {
  step: number;
  action: string;
  query?: string;
  returned?: number;
  new_evidence?: number;
  sufficient?: boolean;
  reason_code?: string;
  missing?: string[];
  next_queries?: string[];
  reason?: string;
  action_taken?: string;
  outcome?: string;
  n_contexts?: number;
  refusal?: boolean;
  selected_mode?: string;
  reasons?: string[];
};

export type AgentBudget = {
  steps: number;
  retrievals: number;
  llm_calls: number;
  elapsed_ms: number;
  limits: {
    max_steps: number;
    max_retrievals: number;
    max_llm_calls: number;
    timeout_seconds: number;
  };
};

type Props = {
  route?: { requested_mode?: string; selected_mode?: string; reasons?: string[] };
  trace?: AgentStep[];
  budget?: AgentBudget;
  degraded?: boolean;
  finishReason?: string | null;
};

const modeName: Record<string, string> = { direct: "快速问答", agent: "深度检索", auto: "自动选择" };
const routeName: Record<string, string> = {
  forced_agent: "手动选择深度检索", zero_recall: "首次检索无结果",
  complex_query: "问题需要综合分析", simple_query_with_evidence: "已有证据，先直接作答",
  direct_refusal_escalation: "快速问答未能回答，升级为深度检索",
};
const actionName: Record<string, string> = {
  route: "选择路径", retrieve: "检索证据", grade: "评估证据",
  fallback: "降级处理", stop: "停止", answer: "生成回答",
};

function summary(step: AgentStep): string {
  switch (step.action) {
    case "route": return `${modeName[step.selected_mode ?? ""] ?? step.selected_mode ?? "未知路径"} · ${(step.reasons ?? []).map((reason) => routeName[reason] ?? reason).join("；")}`;
    case "retrieve": return `查询：${step.query ?? ""} · 命中 ${step.returned ?? 0} 条，新增证据 ${step.new_evidence ?? 0} 条`;
    case "grade": return `证据${step.sufficient ? "充足" : "不足"} · 原因 ${step.reason_code ?? "未提供"}${step.next_queries?.length ? ` · 后续检索：${step.next_queries.join("；")}` : ""}`;
    case "fallback": return `原因 ${step.reason ?? "未提供"} · 处理 ${step.action_taken ?? "未提供"}`;
    case "stop": return `原因 ${step.reason ?? "未提供"}`;
    case "answer": return `结果 ${step.outcome ?? "未提供"} · 使用 ${step.n_contexts ?? 0} 条上下文${step.refusal ? " · 证据不足，拒答" : ""}`;
    default: return "未知步骤";
  }
}

export function AgentTrace({ route, trace, budget, degraded, finishReason }: Props) {
  if (!route && !trace?.length && !budget && !degraded && finishReason !== "length") return null;
  return <section className="border-t border-slate-100 pt-5" aria-label="问答过程">
    <h2 className="text-sm font-semibold">问答过程</h2>
    {route && <p className="mt-2 text-sm text-slate-600">{modeName[route.requested_mode ?? ""] ?? route.requested_mode ?? "自动"} → {modeName[route.selected_mode ?? ""] ?? route.selected_mode ?? "未知"}{route.reasons?.length ? ` · ${route.reasons.map((reason) => routeName[reason] ?? reason).join("；")}` : ""}</p>}
    {budget && <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
      <Badge variant="secondary">步骤 {budget.steps}/{budget.limits.max_steps}</Badge>
      <Badge variant="secondary">检索 {budget.retrievals}/{budget.limits.max_retrievals}</Badge>
      <Badge variant="secondary">模型调用 {budget.llm_calls}/{budget.limits.max_llm_calls}</Badge>
      <Badge variant="secondary">耗时 {(budget.elapsed_ms / 1000).toFixed(1)} 秒（上限 {budget.limits.timeout_seconds} 秒）</Badge>
    </div>}
    {degraded && <p role="status" className="mt-3 text-sm text-amber-700">证据评估未正常完成，已按可用证据降级处理；请检查引用来源。</p>}
    {finishReason === "length" && <p role="status" className="mt-3 text-sm text-amber-700">生成达到长度限制，回答可能未结束。</p>}
    {!!trace?.length && <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
      <summary className="cursor-pointer font-medium">查看执行记录（{trace.length} 步）</summary>
      <ol className="mt-3 space-y-2">{trace.map((step, index) => <li key={`${step.step}-${index}`} className="break-words rounded-md bg-white p-3 text-slate-700">
        <span className="font-medium">{step.step}. {actionName[step.action] ?? step.action}</span><span className="ml-2">{summary(step)}</span>
        {!!step.missing?.length && <p className="mt-1 text-xs text-slate-500">缺少：{step.missing.join("；")}</p>}
      </li>)}</ol>
    </details>}
    {!!trace?.length && <p className="mt-2 text-xs text-slate-500">这里展示的是服务端检索与路由记录，不是模型的内部推理过程。</p>}
  </section>;
}
