# 上传文档生命周期管理

这层解决“上传成功以后怎么管”的问题：查看数据库中的真实状态、重新建库、修改可见范围、删除，
同时保留任务审计。当前版本使用本地持久目录保存原文件，不依赖对象存储。

## 两份清单为什么分开

- `GET /v1/documents` 从 Qdrant 返回当前身份真正可检索的知识库库存，面向 RAG/Agent。
- `GET /v1/uploads` 从 PostgreSQL（本地兼容模式为 JSON）返回上传管理记录，面向用户和管理员。

一篇新文档在 `queued`、`processing` 或 `failed` 时还不一定存在于 Qdrant，但必须能在管理页看到；
反过来，项目原有的离线语料可能在 Qdrant 中，却没有上传数据库记录。因此不能让一个接口同时承担
两种真相源。

## 权限与管理边界

- 普通身份只能管理自己上传的文档。
- 同 tenant 的 admin 可管理该 tenant 全部上传文档。
- 跨 tenant、非 owner 与不存在统一返回 `404`，避免用接口枚举文档归属。
- `private/restricted/tenant` 的 ACL 仍由服务端根据 API key 身份生成；客户端不能提交 tenant、owner
  或原始 ACL。普通 uploader 不能授权给自己不属于的组，tenant 内公开仅 admin 可设置。

## 三条状态流

### 重新建库

```text
ready/failed/access_update_failed
        |
        | 创建新 ingestion_job + Outbox（同一数据库事务）
        v
queued -> processing -> ready / failed
```

原文件和稳定 `document_id` 被复用，旧任务行保留。解析和编码期间旧索引仍可读；新内容准备完成后，
Embedder 才删除旧 points、写入新 points 并原子替换 sidecar。

### 修改权限

```text
ready/failed
   |
   | 创建 held job（无 Outbox，Worker 不可领取）
   v
updating_access
   |
   | 删除旧 Qdrant points + sidecar
   | 原子提交新 ACL、job=queued、Outbox=pending
   v
queued -> processing -> ready

清理失败/进程中断 -> access_update_failed -> 可再次 PATCH
```

修改权限不能只改 PostgreSQL，因为真正参与检索过滤的是每个 Qdrant point 的 ACL payload。这里采用
fail-closed 顺序：先占住文档，再让旧索引下线，最后提交新 ACL 并重建。权限收紧期间宁可暂时查不到，
也不继续用旧的宽权限提供结果。

### 软删除

```text
ready/failed/access_update_failed
        |
        v
deleting -> 删除 points + sidecar + 本地文件 -> deleted
        +--> 清理失败/中断 -> delete_failed -> 重试 DELETE
```

`documents` 和 `ingestion_jobs` 行不物理删除，便于追踪谁上传、处理过几次以及最后状态；原文、解析产物、
向量和 sidecar 会删除。活动任务（`held/queued/retrying/running`）期间拒绝删除，避免 Worker 与删除操作
同时写同一篇文档。

## 一致性与恢复

PostgreSQL 行锁串行化同一文档的状态切换，Outbox 保证已激活的重建任务最终会进入 Redis。权限修改
的 `held` 状态和删除的 `deleting` 状态若超过 Worker stale 阈值，会被 control-worker 转成可重试失败；
Qdrant 按 `doc_id` 删除、sidecar 不存在时跳过、本地目录缺失时跳过，因此重复清理是幂等的。

当前明确边界：原文件只存本机持久卷，所以跨主机部署 Worker 前仍需接入 S3/OSS/MinIO；对象存储不在
本次生命周期 V1 范围内。

## 可用于项目描述的要点

为多租户 Agentic RAG 增加文档全生命周期管理：基于 FastAPI 提供上传清单、重建、ACL 修改与软删除；
通过 PostgreSQL 行锁和 held job 串行化并发操作，以 fail-closed 顺序重建 Qdrant ACL payload；使用
Outbox、Celery Worker 心跳和 stale recovery 恢复消息丢失、Worker 失联及生命周期中断，并保留任务审计。
