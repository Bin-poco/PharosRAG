# Pharos 路线图

已交付能力见 [README](../README.md) 与各设计/实测文档;本文只记**往哪走**与**明确不做**。
(已落地功能的动机/负结果/实测留档:检索智能见 [TESTING §3](TESTING.md) + [COMPONENT_NOTES](COMPONENT_NOTES.md);
团队服务面见 [DESIGN D10-D12](DESIGN.md) + [OPERATIONS](OPERATIONS.md)。)

## 最近交付

- ✅ **多租户 Markdown/PDF 上传**：FastAPI 接收文件并由服务端身份派生 ACL；Markdown 本地标准化，
  PDF 通过 MinerU 解析后复用 Chunker、Embedding、Qdrant 与 sidecar 建库链。
- ✅ **可靠摄取任务**：PostgreSQL 保存文档/任务/Outbox，Redis + Celery 异步执行；支持指数退避、
  Worker 心跳、失联恢复、租约防旧 Worker 覆盖，以及保留历史的人工重试。设计和故障演练见
  [RELIABLE_UPLOAD_JOBS.md](RELIABLE_UPLOAD_JOBS.md)。
- ✅ **上传幂等**：客户端可复用 `Idempotency-Key` 安全重试；服务端按 tenant + owner 隔离，使用
  请求指纹识别冲突，并由数据库唯一索引保证并发请求只创建一份文档、任务和 Outbox。
- ✅ **轻量 Web UI**：Next.js 前端已覆盖 API Key 登录、Direct/Auto/Agent 问答、引用与 trace、
  检索实验、Markdown/PDF 上传、任务状态和文档生命周期管理；前端 lint/build 已纳入 CI。
- ✅ **Agent V2 配对评测**：32 题、三模式、96 次真实运行已完成；记录程序化契约、引用来源组、
  拒答、延迟和调用预算。独立语义裁判与人工签收仍待完成，见
  [V2_BENCHMARK_2026-09-20.md](../eval/V2_BENCHMARK_2026-09-20.md)。

## 候选(按优先级)

- **P1 stats 持久化 + logrotate**:`/v1/stats` 现为进程内、重启归零;请求日志单文件。团队长期运行需
  指标落盘(或接 Prometheus)+ 日志滚动。先观察实际增长速率再决定重量级。
- **P1 密钥吊销审计**:keys 文件编辑 + restart 即吊销,但无"谁在何时被吊销"的审计线索。加一条
  吊销日志 + `pharos keys list/revoke` 子命令。
- **P2 per-key 速率限制**:当前无限流,吞吐天花板 ~3.2 req/s 下单个重度用户可饿死他人。按 key
  令牌桶,超限返回结构化 `rate_limited`。
- **P2 扩展 Office 上传**：当前 HTTP 上传支持 Markdown/PDF；下一步可把 DOCX/XLSX 标准化接入同一
  可靠任务管道，并补 MIME 嗅探、配额和对象存储，避免应用节点共享本地上传目录。
- **P2 表格向检索**:表格题当前 检索 0.750 / 正确 0.688(88 题基线);4 个检索 miss + 2 个大表读数错
  是对称标尺(TESTING §3)。候选:表格块 embed 增强、跨语言查询辅助。
- **P3 LLM 有界重试**(COMPONENT_NOTES N6):DeepSeek 偶发 5xx 现打成 `ask_failed`;观察实际频率后
  决定是否加服务端有界重试(权衡:重试放客户端语义更清晰)。
- **P3 会话内并发去重竞态**(IMPLEMENTATION §3 观察项):单会话并发工具调用时 returned_keys 交错;
  串行调用下无实害,出现实害再加 per-session 锁。

## v2 方向(规模驱动,不预支)

- ✅ **Qdrant server 模式 + 多副本 + 负载均衡(已交付,阶段 A–F,见 [SCALE_OUT.md](SCALE_OUT.md))**:拆 GPU 推理层
  → 应用脱 torch → 嵌入式 Qdrant 转 server → nginx 多副本 + `docker kill` 无感。⚠ 订正原措辞"EmbedConfig 换 url
  即迁移"过度简化:实际还需 `store.py` 三分支 + 全出口透传 `qdrant_url` + 数据迁移 + **server-mode ACL 越权重测**。
  剩余 open:session 粘滞/共享去重、inference 换 vLLM(GPU 排队明显时)、K8s。
- SSE/streaming ask（只有真实长答案等待成为主要体验问题时再做）。

## 明确不做

- **HTTPS/公网终结**:内网信任边界 + API key;要远程走 tailscale 之类隧道,不在应用层做 TLS。
- **SSO/OIDC**:当前规模不值得引入 IdP 依赖;keys 文件 + 重启的轮换足够。
- **跨文档综合难题的检索增强**:评估显示 multi_cross 是研究性问题(仓内 eval 已定论),不追。
