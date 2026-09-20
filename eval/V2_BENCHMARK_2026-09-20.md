# V2 Agent 配对评测摘要（2026-09-20）

## 范围与复现

- Suite：`eval/official_agent_gold_v2.json`，SHA-256 `40e72caf016763097ce7d1adbadcf0f2b85c12c7dcd116c12afddf7395b2cb9d`
- 固定语料：`official-tech-docs-v1`，32 题；single 9、multi_section 6、cross_doc 12、no_answer 5
- 模式：同一题成对运行 `direct`、`agent`、`auto`，共 96 次真实 `/v1/ask` 调用
- 生成模型：`deepseek-v4-flash`
- 裁判：`none`。本报告只使用可程序化验证的响应契约、引用来源组、拒答、路由、调用次数和延迟；不声称答案正确率或忠实度
- Gold 由 AI 辅助编写并完成来源复核，`human_review` 仍为 `pending`

复现命令：

```bash
.venv/bin/python eval/agent_benchmark.py \
  --suite eval/official_agent_gold_v2.json \
  --profile all \
  --judge none
```

原始逐题 JSON/Markdown 报告包含完整答案和证据正文，按仓库策略保存在被忽略的
`eval/benchmark_reports/`，不进入 Git；本文件只提交可核验摘要。

## 结果

| 模式 | 契约通过率 | 引用来源组召回 | 无答案正确拒答 | 平均延迟 | P95 延迟 | Agent 路由率 |
|---|---:|---:|---:|---:|---:|---:|
| Direct | 93.8% | 97.5% | 100.0% | 3744 ms | 8903 ms | 0.0% |
| Auto | 96.9% | 98.8% | 100.0% | 3863 ms | 7864 ms | 25.0% |
| Agent | 100.0% | 100.0% | 100.0% | 4595 ms | 8184 ms | 100.0% |

相对 Direct，Auto 的契约通过率提高 3.1 个百分点、引用来源组召回提高 1.2 个百分点，
平均延迟增加 119 ms；Agent 分别提高 6.2 和 2.5 个百分点，平均延迟增加 851 ms。
Agent 平均执行 1.75 次检索和 2.38 次 LLM 调用；Auto 为 1.44 次检索和 1.69 次 LLM 调用。

差异集中在 cross_doc：Direct 契约通过率 83.3%、引用来源组召回 94.4%；Auto 为
91.7%/97.2%；Agent 为 100%/100%。single、multi_section 与 no_answer 三类的三种模式
均通过程序化契约。

## 三个失败与 Agent 的实际收益

1. `cross_fastapi_background_celery`：Direct 和 Auto 只引用 FastAPI BackgroundTasks 与
   Celery first steps，明确表示缺少任务幂等和 late acknowledgment 证据，因此未覆盖要求的
   `celery__tasks`。强制 Agent 经过三次检索补齐该来源并通过。
2. `cross_docker_networking`：Direct 已回答服务名、容器端口和 bridge，但没有引用专门的
   `docker__port_publishing`。Agent 补齐该来源并通过；Auto 的首次 Direct 答案触发拒答升级，
   随后进入 Agent 路径并通过。

这说明有限步 Agent 的可测收益主要是跨文档来源覆盖，而不是所有问题都需要多轮检索。
Auto 在本轮只把 25% 的问题路由到 Agent，整体延迟接近 Direct，同时修复了其中一个
Direct 跨文档失败；另一个题被误判为证据充足，仍未升级。

## 不能从本轮推出的结论

- `PASS` 不等于语义答案正确，只表示状态、拒答和要求的引用来源组等程序化契约通过。
- 未启用独立裁判，因此正确性、忠实度和必需事实召回保持为空；不能将 100% Agent 契约率写成
  “答案正确率 100%”。
- 32 题来自固定官方技术文档，规模仍小；单次在线运行也不能代表长期 P95 或故障率。
- Gold 尚未由独立人类逐题签收。对外或简历可使用“32 题、96 次配对运行”的工程数据，
  但语义效果数字应在人工审核或异厂双裁判后再发布。

## 下一步

优先分析 Auto 对 `cross_fastapi_background_celery` 的“证据充足”误判，使复杂问题在缺少指定子主题
时升级补检。修复后应复跑同一 suite 并与本报告做配对比较；不要改变题目后直接声称指标提升。
