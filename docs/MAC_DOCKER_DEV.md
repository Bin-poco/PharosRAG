# Apple Silicon + 在线模型开发环境

这套配置用于 Mac 学习与二次开发，不替换仓库原有的 NVIDIA/WSL2 部署。目标是保留完整的 RAG、FastAPI、Qdrant、ACL、MCP 和评估代码，只把本地 CUDA 推理层替换成在线 API。

## 1. 架构

```text
浏览器 / curl / MCP Agent
          |
          v
Pharos FastAPI :8787  -----> DeepSeek（生成答案）
     |          +---------> PostgreSQL（文档与任务状态）
     |          +---------> Redis（Celery 消息）
     |                            |
     |                 +----------+----------+
     |                 |                     |
     |          Ingestion Worker       Control Worker
     |          （解析与建库）          （补投与恢复）
     |                 |                     |
     +-----------------+---------------------+-----> Qdrant :6333（向量检索）
                                  |
                         cloud-inference :8900
                                  |
                         阿里云百炼（Embedding + Rerank）
```

`pharos` 负责 API、检索、引用、权限和问答；`worker` 负责耗时的文档摄取；`scheduler` 定时发送
维护任务，`control-worker` 独立执行 Outbox 补投和失联恢复，避免被长时间 PDF 解析阻塞；PostgreSQL 是任务状态的唯一真相来源，Redis 只传递消息。`qdrant` 保存
向量，`cloud-inference` 把内部推理协议翻译成百炼 API。宿主机源码挂载进容器，API 服务可自动
重载；Worker 代码修改后执行 `docker compose ... restart worker control-worker scheduler`。

## 2. 首次配置

```bash
cp .env.mac.example .env.mac
mkdir -p data/parsed data/index data/secrets
cp deploy/pharos.keys.mac.json.example data/secrets/pharos.keys.json
```

打开 `.env.mac`，至少填写：

- `DASHSCOPE_API_KEY`：阿里云百炼 API Key；
- `DEEPSEEK_API_KEY`：DeepSeek API Key；
- `DASHSCOPE_RERANK_URL`：如果控制台给出带业务空间 ID 的专属地址，必须粘贴完整地址覆盖默认值。

密钥文件和 `.env.mac` 都已被 Git 忽略。示例 API key 只绑定 `127.0.0.1` 的本地开发环境；将来部署到服务器时必须重新生成。

## 3. 启动和观察容器

先单独启动完全不需要云端密钥的 Qdrant：

```bash
docker compose --env-file .env.mac -f compose.mac.yml up -d qdrant
docker compose --env-file .env.mac -f compose.mac.yml ps
```

填好两个云端密钥后，构建并启动整套服务：

```bash
docker compose --env-file .env.mac -f compose.mac.yml up -d --build
docker compose --env-file .env.mac -f compose.mac.yml ps
curl http://127.0.0.1:8900/healthz
curl http://127.0.0.1:8787/healthz
```

查看日志：

```bash
docker compose --env-file .env.mac -f compose.mac.yml logs -f cloud-inference pharos worker control-worker scheduler
```

停止但保留向量数据：

```bash
docker compose --env-file .env.mac -f compose.mac.yml down
```

不要随手加 `-v`；`down -v` 会删除 Qdrant 的本地持久卷，需要重新建库。

## 4. 准备和导入技术文档

Pharos 的批量建库输入是 MinerU 解析结果。每篇文档一个子目录，放在 `data/parsed/` 下，子目录里应有 `content_list.json`、布局信息和提取出的图片。例如：

```text
data/parsed/
  kubernetes__deployment-guide/
    content_list.json
    ...
  fastapi__official-docs/
    content_list.json
    ...
```

仓库另带一套可复现的官方技术文档语料，不需要 MinerU Token。清单固定了 FastAPI 10 篇、
Docker 11 篇、Qdrant 12 篇、Celery 4 篇，共 37 篇 Markdown/RST 文档及对应 Git revision、
许可证和原始来源；内容覆盖 API 开发与部署、容器网络/存储/安全、向量数据库检索/多租户/
快照/扩容，以及异步任务的重试、路由和 Worker 运维，可用于构造单文档、跨章节和跨文档
Agentic RAG 评估题。下面的命令会下载并转换到同一标准目录：

```bash
PYTHONPATH=src python3 -m pharos import-markdown \
  --manifest config/official_tech_docs.json \
  --dest data/parsed
```

只增量导入某一篇可加 `--only docker__bind_mounts`；它按 `doc_id` 前缀筛选，不会重新下载其他文档。

转换结果会保留 `source.md` 或 `source.rst`、`metadata.json` 和 `*_content_list.json`。其中
`data/` 是本地可再生数据，不提交 Git；文档清单和导入代码会提交，因此换一台机器仍能重建相同语料。

导入前先停问答服务，避免 sidecar 一边写一边读；Qdrant 和在线推理服务保持运行：

```bash
docker compose --env-file .env.mac -f compose.mac.yml stop pharos
docker compose --env-file .env.mac -f compose.mac.yml run --rm --no-deps pharos \
  pharos index --corpus /data/parsed --tenant demo --visibility public
docker compose --env-file .env.mac -f compose.mac.yml up -d pharos
curl http://127.0.0.1:8787/readyz
```

建库会调用百炼 Embedding，重排只在查询时调用，因此两者都会产生少量 API 费用。Embedding 模型或维度一旦更换，必须新建 collection 或清空后完整重建，不能在同一个向量库里混用。

### 上传单篇 Markdown 或 PDF

开发 key 需要 `roles` 含 `uploader`(或 `admin:true`)。示例 keys 文件已包含该角色;修改本机
`data/secrets/pharos.keys.json` 后需重启 `pharos` 容器。

```bash
source .env.mac
curl -sS -X POST http://127.0.0.1:8787/v1/documents \
  -H "X-API-Key: $PHAROS_DEV_API_KEY" \
  -F "file=@./README.md;type=text/markdown" \
  -F "access_scope=private"
```

PDF 额外需要 MinerU Token。先从 `.env.mac.example` 复制相关配置，把真实 Token 填入本机
`.env.mac` 的 `MINERU_TOKEN_A`，再重建或强制重建容器使环境变量生效：

```bash
docker compose --env-file .env.mac -f compose.mac.yml up -d --force-recreate pharos

source .env.mac
curl -sS -X POST http://127.0.0.1:8787/v1/documents \
  -H "X-API-Key: $PHAROS_DEV_API_KEY" \
  -F "file=@./docs/example.pdf;type=application/pdf" \
  -F "access_scope=private"
```

PDF 会先上传到 MinerU 在线精准解析服务，因此原始文档会离开本机；涉及内部或敏感材料时应先
确认组织的数据合规要求，或以后把客户端切换到自建 MinerU 服务。`stage=mineru_parsing` 表示仍在
等待解析，完成后会继续变成 `chunking`、`embedding`、`ready`。临时故障时会显示
`job_status=retrying, stage=waiting_retry`，不需要手动重复上传。

记住响应中的 `job_id`，查看处理状态:

```bash
curl -sS http://127.0.0.1:8787/v1/jobs/job_xxx \
  -H "X-API-Key: $PHAROS_DEV_API_KEY"
```

任务达到最大自动重试次数后会变成 `failed`。问题修复后可创建新的重试任务（响应会给出新
`job_id`，旧任务仍保留）：

```bash
curl -sS -X POST http://127.0.0.1:8787/v1/jobs/job_xxx/retry \
  -H "X-API-Key: $PHAROS_DEV_API_KEY"
```

权限范围示例:

```bash
# 分享给当前用户所属 g_dev
-F "access_scope=restricted" -F "groups=g_dev"

# tenant 内公开，仅 admin
-F "access_scope=tenant"
```

上传原文与标准化产物保存在 `data/uploads/`，任务状态保存在 PostgreSQL 持久卷。新文档就绪后会直接进入现有
Qdrant collection，无需停止问答服务。Markdown 本地转换；PDF 的 MinerU 结果会保留
`content_list.json`、可选 `layout.json` 和提取图片，以支持页码引用、表格及多模态向量。

## 5. 发起一次完整问答

```bash
source .env.mac
curl -s http://127.0.0.1:8787/v1/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $PHAROS_DEV_API_KEY" \
  -d '{"query":"这套系统如何处理检索失败？","top_k":6,"rerank":true,"include_contexts":true}'
```

如果只想验证检索、不调用 DeepSeek，把地址改为 `/v1/retrieve`，请求体可保持相近结构。这样更适合先调 chunk、召回和 rerank，再调生成答案。

### 运行 Agentic RAG 冒烟矩阵

仓库提供 10 条基于上述官方语料的真实接口用例，覆盖普通问答、自动路由、有限步 Agent、跨文档
引用和无证据拒答。`.env.mac` 中的变量默认没有导出给 Python 子进程，所以运行前用 `set -a`：

```bash
set -a; source .env.mac; set +a
.venv/bin/python eval/service_smoke.py --profile quick
.venv/bin/python eval/service_smoke.py --profile all
```

`quick` 跑 4 条，适合日常修改后检查；`all` 跑全部 10 条，适合提交前检查。它会实际调用在线模型，
因此会产生少量 API 费用。它检查路由、预算、引用来源、拒答和截断等稳定契约，不把模型措辞逐字
固定成断言；正式准确率、召回率和忠实度仍使用 `eval/run_eval.py` 的 gold 评估流程。

## 6. 日常开发节奏

1. 修改 API/检索代码：Pharos 容器自动重载；修改任务代码后重启 `worker control-worker scheduler`；
2. 修改 `src/cloud_inference/`：在线推理适配器自动重载；
3. 改 Python 依赖或 Dockerfile：重新执行 `up -d --build`；
4. 改 `.env.mac`：执行 `up -d --force-recreate` 让容器重新读取；
5. 用 `logs -f` 看调用链，用 `/readyz` 看 Qdrant、collection 和在线推理是否完整就绪。

可靠上传队列的设计、状态机、故障演练和面试讲法见 [RELIABLE_UPLOAD_JOBS.md](RELIABLE_UPLOAD_JOBS.md)。
