# Pharos 前端

技术栈：Next.js App Router、TypeScript、Tailwind CSS、shadcn/ui。页面提供个人密钥连接、`direct / auto / agent` 问答、引用来源、Dense/Sparse/混合检索实验室、正文与章节目录、Markdown/PDF 上传及任务状态。上传者或管理员还可管理权限、重建索引、重试失败任务与删除文档。

问答卡片在 `auto/agent` 模式下展示后端返回的路由原因、执行步骤和步骤/检索/模型调用预算；发生控制器降级或答案长度截断时单独提示。`direct` 没有 Agent trace；执行记录不是模型内部推理。

## 本地运行

先按仓库根目录的 [Mac Docker 开发指南](../docs/MAC_DOCKER_DEV.md) 启动 FastAPI 后端，确认 `http://127.0.0.1:8787/healthz` 返回 `ok`。前端需要后端处于多身份 keys 模式；登录时填你自己的 API Key。

在 `frontend` 目录中执行：

```bash
cp .env.local.example .env.local
npm ci
npm run dev
```

打开 `http://localhost:3000`。如果后端地址不是 `127.0.0.1:8787`，修改 `.env.local` 中的 `PHAROS_API_URL`。这个变量只供 Next.js 服务端读取；不要将真实 API Key 写入 `.env.local` 或 `NEXT_PUBLIC_*` 变量。

首次登录会由 Next.js 调用 FastAPI 的 `GET /v1/me` 验证密钥。后续浏览器请求走同源 `/api/*`，Next.js 从 HttpOnly Cookie 取出密钥并转发到 FastAPI。上传按钮按 `/v1/me` 返回的角色显示；文档访问与上传权限仍由 FastAPI 每次请求校验。

## 检查

```bash
npm run lint
npm run build
```

后端和前端都运行时，可从 `frontend` 目录执行真实接口联调（会创建并清理一份临时 Markdown 文档，还会调用在线问答模型）：

```bash
set -a
source ../.env.mac
set +a
PHAROS_WEB_URL=http://127.0.0.1:3000 npm run test:smoke
```

脚本经前端 `/api/*` 验证登录/登出、鉴权、文档正文与大纲、检索与上下文扩展、三种问答模式、上传任务、重建索引、权限更新和删除。默认按 `http://127.0.0.1:3001` 访问前端；使用其他端口时设置 `PHAROS_WEB_URL`。只复查文档链路、不重复调用在线问答模型时可设置 `PHAROS_SMOKE_SKIP_ASK=1`。

双身份实机验收需同一 tenant 的两个不同密钥：第一位为有上传权限的管理员，第二位为非管理员读者。将第二位的密钥通过 `PHAROS_SECOND_API_KEY` 注入当前终端（不要写进仓库）；先确认后端 `/readyz` 就绪，然后在 `frontend` 目录运行 `npm run test:two-user`。脚本会上传一份随机命名的私有 Markdown，检查双方清单、正文、检索、问答引用与任务管理；再改为租户可见并重新检查，最后撤回私有权限并清理临时文档。需要运行中的建库 worker/向量库和在线问答模型，可能产生服务调用费用。两把密钥必须代表不同用户；第二位不能是管理员，否则 ACL 隔离无法成立。脚本异常时会尽力删除临时文档；如果输出 `CLEANUP FAILED`，请按报告的文档 ID 手工检查/删除。

若要额外验证 MinerU 的真实 PDF 解析，可准备一份可丢弃的 PDF 并运行 `PHAROS_WEB_URL=http://127.0.0.1:3000 PHAROS_SMOKE_PDF_PATH=/绝对路径/test.pdf npm run test:pdf`。脚本会上传一份私有副本、等待解析并删除；如需核对提取出的特定文字，设置 `PHAROS_SMOKE_EXPECT_TEXT`。这一步会调用在线 MinerU 服务。

2026-09-19 此前本地联调结果：前端 lint/build 通过；后端测试 `328 passed, 12 skipped`。真实服务中已验证匿名拦截、密钥登录/登出、文档清单/内容/大纲、检索/扩展/分组检索、`direct/auto/agent` 问答、Markdown 与 PDF 上传、任务状态、重建索引、权限更新和删除。新增前端管理接口的联调脚本也已通过，临时文档均已删除。重试接口仅验证了对非失败任务返回 `409`；失败任务的成功重试和非管理员用户的实机权限隔离仍由自动化测试覆盖，未做本轮在线演练。上面的双身份脚本是新补的验收路径，不能把编写脚本视为实机验收通过。

当前本地构建使用 webpack；在此开发环境中，Turbopack 构建的 CSS 子进程绑定端口会失败。

2026-09-19 本轮复验：新增问答过程展示后，前端 lint/build、接口烟测均通过；后端全量测试 `329 passed, 12 skipped`。双身份实机脚本已通过：临时非管理员读者在私有状态下无法访问文档、检索结果、问答引用或任务/管理接口；管理员发布到租户后读者可以读取、检索并得到带引用的答案；撤回私有后再次不可访问。临时上传文档已删除，临时读者密钥已从 keys 文件移除，原始内容校验一致且后端重启就绪。为保护原有密钥，恢复后文件权限收紧为 `600`。
