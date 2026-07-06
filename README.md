# CodeReview Agent

面向 Java、Python 项目的可解释、可评测 AI 代码审查平台。

项目计划通过 Tree-sitter 建立带文件路径、符号和行号的代码知识库，使用
PostgreSQL 全文检索、pgvector 与 RRF 组成 Hybrid RAG，再通过有界
LangGraph 工作流生成并校验证据充分的审查报告。

## 当前状态

**Module 02：认证与项目** 已完成，下一阶段将进入安全上传。开发采用
单子任务验收制，不提前创建未使用的模块或声称尚未测得的效果。

已完成：

- 仓库与协作规范。
- FastAPI 应用工厂、类型化配置、结构化日志和统一错误响应。
- `/api/v1/health/live` 与 `/api/v1/health/ready` 健康检查。
- PostgreSQL、Redis 异步客户端、生命周期管理与就绪探针。
- Vue3、TypeScript、Pinia、Element Plus 基础页面与后端状态展示。
- Ruff、MyPy、Pytest、ESLint、Prettier、Vitest 与 GitHub Actions。
- User、Project、ProjectFile 持久化模型及 Alembic 初始迁移。
- Argon2 密码哈希、短期 JWT 登录和当前用户认证。
- 带资源所有权校验的项目列表、详情和删除接口。

## 核心技术决策

- Java/Python 统一封装在可扩展 `LanguageAdapter` 中。
- DeepSeek V4 负责规划、审查和语义复核。
- 千问 `text-embedding-v4` 负责生成 1024 维代码向量。
- PostgreSQL 全文检索与 pgvector 结果通过 RRF 融合。
- 确定性 `EvidenceVerify` 在 Critic 前验证路径、行号、证据和 Chunk 归属。
- 普通自动化测试使用 Fake Provider，不产生模型调用费用。

## 文档

- [完整项目大纲](docs/project-outline.md)
- [开发协作规范](CONTRIBUTING.md)
- [仓库内 AI 协作约束](AGENTS.md)

## 后端本地运行

使用 Python 3.12，并提前启动 PostgreSQL 与 Redis。复制
`backend/.env.example` 为 `backend/.env`，按本机环境修改连接地址：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m alembic upgrade head
uvicorn app.main:app --reload
```

启动后可访问：

- `GET http://127.0.0.1:8000/api/v1/health/live`
- `GET http://127.0.0.1:8000/api/v1/health/ready`
- `POST http://127.0.0.1:8000/api/v1/auth/register`
- `POST http://127.0.0.1:8000/api/v1/auth/login`
- `GET http://127.0.0.1:8000/api/v1/projects`
- `GET http://127.0.0.1:8000/docs`

`live` 只检查 API 进程；`ready` 会检查 PostgreSQL 和 Redis，任一依赖不可用时
返回 `503 SERVICE_NOT_READY`。项目不提供 Docker 一键编排。

## 前端本地运行

使用 Node.js 24 和 pnpm 11：

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

开发服务器默认访问 `http://127.0.0.1:5173`，并将 `/api` 请求代理到
`http://127.0.0.1:8000`。

## 完整检查

后端检查命令见 [CONTRIBUTING.md](CONTRIBUTING.md)。前端可以运行：

```powershell
cd frontend
pnpm run check
```

同样的检查会在功能分支、Pull Request 和 `main` 上由 GitHub Actions 执行。

## 开发边界

v1 不执行、编译或导入用户代码，不允许 Agent 使用 Shell、外部网络或任意
SQL，也不承诺替代人工审查或成熟 SAST 产品。README 中的实验数据只会来自
可复现 Benchmark。

## License

[Apache License 2.0](LICENSE)
