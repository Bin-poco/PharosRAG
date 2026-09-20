# 可靠性边界修复（2026-09-19）

范围：项目结构审阅中确认的三个问题。未调整回答输出长度策略、用户体系或现有知识库。

## 1. 失去租约的 Worker 不能发布产物

原问题：只在阶段/终态写数据库时检查 Worker，长时间编码后旧执行仍能删除、覆盖 Qdrant 和 sidecar。

- `repository.publish_guard` 在 PostgreSQL 事务中同时锁定当前文档与任务，校验 job、worker、attempt、running 状态。
- 解析/编码在锁外完成；删旧索引、写新向量、替换 sidecar 和发布解析目录都在同一个保护区中。
- 锁内不调用另一个仓储写事务；发布结束刷新心跳，避免恢复程序把刚完成发布的任务误判失联。
- 每次 Celery 执行有独立 Worker 标识；解析目录与 sidecar 临时文件也使用唯一名字。
- 丢失执行权时只清理本次临时产物，不修改正式目录和索引。

边界：文件仓储仅支持单进程；SQLite 使用 `BEGIN IMMEDIATE` 兼容测试。
这不是 PostgreSQL、Qdrant、文件系统之间的分布式事务；发布中途服务崩溃、存储错误或数据库连接丢失
仍需要失败重试/恢复，不承诺跨存储原子提交或 exactly-once。

## 2. Agent 请求截止时间

- 同一请求使用绝对截止时间，覆盖检索、证据判断、上下文准备和生成；超时返回 `stop: timeout`、`degraded: true`，不接受迟到答案。
- 检索/控制器超时不再触发下一轮补检或降级生成。
- LLM 使用剩余时间作为网络超时，并在 Agent 请求内关闭 SDK 隐式重试。
- 远程 embedding/rerank 的网络超时、重试和退避共享剩余预算。
- 阻塞工作使用每进程最多 16 个槽位；未退出的调用继续占槽，避免超时后无限创建线程或排队。

边界：截止时间限制的是本服务的等待和后续动作（允许线程调度误差），不能撤销远端已经收到的推理，
也不能保证供应商停止计费。Python 不强杀正在执行的线程；适配器有 I/O 超时，迟到结果被丢弃。
独立 `direct` 问答保持原来配置，不受 Agent 截止时间控制。输出截断策略仍为暂缓项。

## 3. Nginx 禁止写请求自动重放

- 文档和任务生命周期路由：`proxy_next_upstream off`。
- 其余路由保留默认安全重试，不再启用全局 `non_idempotent`。
- 请求发送后的 POST/PATCH 不再为了故障切换而重复执行；不能再用历史 kill 测试宣称写接口无感恢复。
- 未实现客户端幂等键；用户主动重复提交仍可能创建两份文档。

## 验证

新增回归覆盖旧执行在解析/编码后复活、执行权转交/新任务/删除后的拒绝发布、临时文件隔离、
检索/控制器/生成超时、迟到结果丢弃、线程容量边界、网络预算与代理配置。

```bash
python -m pytest -q
docker exec -i pharos-mac-app python - < scripts/check_publication_lock.py
```

PostgreSQL 验证在随机独立 schema 中运行，结束自动清理，不触碰应用现有表：确认文档与任务行均被锁定、
失联恢复跳过发布区、发布后心跳刷新、执行权转交后拒绝旧 Worker。

本轮实测结果：

- 本地全量回归：`355 passed, 7 skipped`；跳过项不计入通过。
- 真实 PostgreSQL 隔离校验：4 项通过，临时 schema 已删除。
- `nginx:1.27-alpine` 容器内 `nginx -t`：通过；临时校验容器自动删除，未启动代理监听端口。
- 确认数据库没有排队/运行任务后，已重启 ingestion worker、control worker、scheduler 以加载改动；
  FastAPI `/readyz` 返回 ready，两个 Celery worker 均回复 pong。
- 本轮未调用付费模型，未修改实际知识库；未做多机故障压测，未提交或推送 Git。
