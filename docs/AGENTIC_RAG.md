# 有限步 Agentic RAG 设计

## 目标与边界

这套实现解决“一次检索取不全跨章节、跨文档证据”的问题，但不把任意工具执行权交给模型。
Agent 只能在服务端固定状态机里执行三类动作：检索、判断证据、生成答案。它没有长期记忆，
不能上传、删除或修改文档，也不能修改 tenant、principals 或 ACL。

三个运行模式：

- `direct`：原闭管道，低延迟、容易评估，是默认模式；
- `agent`：强制运行证据判断与有限补检，用于复杂问题和演示；
- `auto`：先以低成本检索并路由。简单且有证据的问题直接生成；明显综合型问题、零召回或
  direct 拒答才升级到 Agent。

## 状态机

```text
请求
  │
  ├─ direct ──▶ 检索 ──▶ ACL/上下文预算 ──▶ 生成
  │
  └─ agent/auto ─▶ 首次检索 ─▶ ACL/上下文预算
                         │
                         ├─ auto + 简单 + 有证据 ─▶ 直接生成
                         │                              └─ 拒答则升级
                         ▼
                    证据充分性判断
                         │
              ┌──────────┴──────────┐
              │充分                 │不足
              ▼                     ▼
          带引用生成         生成定向检索词
                                    │
                             补检、合并、去重
                                    │
                       回到证据判断（预算内）
                                    │
                  无法继续补检但已有证据
                                    ▼
                         基于已有证据尽力回答
```

最终状态只有三种：带引用答案、明确“证据不足”拒答、控制器异常后降级到已有 direct 生成。
其中带引用答案既可能来自“证据充分”，也可能是补检预算结束后的 `best_effort_*`：它仍然只允许
根据已通过 ACL 的证据作答，缺失部分应明确说明不知道，而不是丢弃已经找到的有效证据。

## 为什么不是“让模型随便调用工具”

开放式 ReAct 循环很容易产生不可控调用次数、重复检索和难以复现的行为。这里采用显式状态机：

1. 代码决定允许哪些动作和何时停止；
2. LLM 只输出证据判断 JSON 与最多两条定向检索词；
3. 最终答案继续使用原 `Generator` 的 grounding prompt 和 citation 解析；
4. 每一步都有结构化 trace，可测试、可展示、可统计。

这仍是 Agentic RAG，因为模型会根据当前证据动态决定是否继续检索以及检索什么；只是执行边界由
系统控制，而不是让模型拥有无限循环和任意工具。

## 数据与调用链

核心入口：

- `src/pharos/service.py`：校验身份和参数，选择 direct/agent/auto，返回 route/trace/budget；
- `src/pharos/agentic.py`：路由、证据控制器、请求级状态和停止条件；
- `src/generator/generate.py`：共享检索、ACL 后证据整理、最终生成和引用映射；
- `src/pharos/engine.py`：从配置构造 Agent 预算。

Agent 多轮结果按 `chunk_id` 去重。所有轮次都携带服务端解析出的同一个 `User` 和相同过滤参数，
模型不能在补检词中改变身份。证据控制器和最终生成器都只读取
`Generator.prepare_contexts()` 输出，因此共享 ACL 复核、表格 `content_raw` 补回和上下文预算。

证据控制器有独立的字符预算。实现不会让排在最前面的长章节独占预算，而是先给每条证据公平配额；
每条证据又优先展示实际命中的小块，并从扩展章节中提取与 query 相关的窗口。这样即使目标事实位于
同一章节较后面的兄弟块，控制器也能看到。该裁剪只用于“是否继续检索”的判断，最终生成仍读取完整
上下文，不会把裁剪版当成回答材料。

## 控制器输出契约

证据控制器必须只返回 JSON：

```json
{
  "sufficient": false,
  "reason_code": "missing_production_guidance",
  "missing": ["生产环境持久化建议"],
  "next_queries": ["Docker production volume persistence"]
}
```

服务端验证 `sufficient` 类型、列表长度、去重和字符串长度。控制器不负责回答用户，也不会把其
自然语言推理过程暴露给 API。无效 JSON、上游超时或控制器异常会记录稳定原因码并降级，第三方
异常原文不会返回给客户端。

## 硬预算与停止条件

默认值：最多 10 个 trace 步骤、3 次检索、4 次 LLM 调用、45 秒、每轮最多 2 条补检词。
LLM 调用预算同时包含证据判断与最终生成。以下任一条件触发停止：

- 控制器认为证据充分：生成答案；
- 没有新的检索词或检索预算耗尽：若已有安全证据且还留有一次生成和两个 trace 步骤，基于已有证据
  尽力回答；否则拒答；
- LLM、步骤或时间预算耗尽：拒答；
- 控制器异常：使用已有安全证据降级到 direct；
- 最终生成上游失败：由 API 返回可重试的 `agent_failed`。

配置项见 `.env.example` 的 `PHAROS_AGENT_*`。

## Trace 示例

```json
[
  {"step":1,"action":"route","requested_mode":"agent","selected_mode":"agent","reasons":["forced_agent"]},
  {"step":2,"action":"retrieve","query":"设计 Docker 持久化方案","returned":4,"new_evidence":4},
  {"step":3,"action":"grade","sufficient":false,"reason_code":"missing_prod","missing":["生产建议"],
   "next_queries":["Docker production volume backup"]},
  {"step":4,"action":"retrieve","query":"Docker production volume backup","returned":3,"new_evidence":2},
  {"step":5,"action":"grade","sufficient":true,"reason_code":"complete","missing":[],"next_queries":[]},
  {"step":6,"action":"answer","outcome":"evidence_sufficient","n_contexts":6,"refusal":false}
]
```

Trace 是行为审计，不是 chain-of-thought：它只包含动作、数量、稳定原因码和实际使用的检索词。

## 测试与效果评估

`tests/test_agentic.py` 覆盖自动路由、两轮补检与证据合并、控制器异常降级、ACL 双重防线、
证据字符预算、检索/步骤预算停止和两个 HTTP 入口。`eval/official_agent_smoke.json` 还提供了 10 道
基于固定版本 FastAPI、Docker、Qdrant、Celery 官方文档的生产 API 烟测，覆盖 direct/agent/auto、
跨文档综合、引用范围、trace、预算和空作用域拒答；当前本地真实服务结果为 10/10 通过。

烟测证明链路和关键不变量能工作，但不能证明 Agent 比 direct 更好。

当前已经增加 `eval/official_agent_gold.json`：26 道逐题编写、可人工复核的固定考卷，包含 5 道单文档
事实题、7 道单文档跨章节题、9 道跨文档综合题和 5 道无答案题。每题带参考答案、必需事实 ID、
文档作用域和引用来源组。`eval/agent_benchmark.py` 直接调用真实 `/v1/ask`，对同一题成对运行
direct、agent、auto，记录：

- 答案正确率与引用正确率；
- 无答案问题的正确拒答率；
- 平均/P95 延迟；
- 每题检索次数、LLM 调用次数和估算成本。

其中接口契约、引用来源、拒答和延迟可程序化统计；答案正确性、忠实度和必需事实覆盖需启用裁判。
DeepSeek 同厂裁判只属于 Tier 1 趋势指标，正式对外数字还需人工抽检或异厂双裁判。只有结果证明
多跳子集有收益后，才能在简历中写“提升了多少”；否则应诚实报告 Agent 的代价或负结果，而不是
只描述功能已实现。

初版 gold 是 AI 辅助、依据固定官方语料整理的 starter set，不等同于领域专家标注。简历中可以描述
“建立了可复核的 golden set 与 paired benchmark”，但在人工逐题审核前不能写“人工标注数据集”。

### 首次完整基线（2026-09-12）

在本机 Docker 真实服务、当前 37 篇固定官方语料和 `deepseek-v4-flash` 配置上，26 道题分别运行
direct/agent/auto，共 78 次。以下为单次 Tier 1 同厂裁判结果：

| 模式 | 正确性 | 忠实度 | 必需事实召回 | 平均延迟 | P95 延迟 | Auto/Agent 路由 |
|---|---:|---:|---:|---:|---:|---:|
| direct | 96.2% | 100% | 97.4% | 3689 ms | 8409 ms | 0% |
| agent | 100% | 100% | 98.7% | 4670 ms | 9021 ms | 100% |
| auto | 100% | 100% | 98.7% | 4341 ms | 7783 ms | 30.8% |

三种模式的引用来源组召回与无答案题明确拒答率均为 100%。Agent 和 auto 相对 direct 的配对正确性
增加 3.8 个百分点，实际只对应 1 道跨 FastAPI/Celery 文档题：direct 漏掉任务幂等与 `acks_late`，
Agent 补检后覆盖；样本量太小，不能外推成稳定提升。代价是 agent 平均多 981 ms，auto 多 652 ms。

本轮还发现两次 `finish_reason=length`：agent 的 Qdrant 多租户答案、direct 的 hybrid+quantization
答案虽然被裁判判为正确忠实，但输出被截断。这应作为下一轮产品优化项，而不是从分数里隐藏。
由于 gold 尚未人工签字、裁判与被测模型同厂、每题只运行一次，这组数字是开发基线，不是可直接放入
简历的最终实验结论。
