# CodeReview Agent

面向 Java、Python 项目的可解释、可评测 AI 代码审查平台。

项目计划通过 Tree-sitter 建立带文件路径、符号和行号的代码知识库，使用
PostgreSQL 全文检索、pgvector 与 RRF 组成 Hybrid RAG，再通过有界
LangGraph 工作流生成并校验证据充分的审查报告。

## 当前状态

当前处于 **Module 01：工程脚手架**。开发采用单子任务验收制，不提前创建
未使用的模块或声称尚未测得的效果。

已完成：

- 仓库与协作规范。
- FastAPI 应用工厂、类型化配置、结构化日志和统一错误响应。
- `/api/v1/health/live` 与 `/api/v1/health/ready` 健康检查。
- Vue3、TypeScript、Pinia、Element Plus 基础页面与后端状态展示。

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

使用 Python 3.12：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

启动后可访问：

- `GET http://127.0.0.1:8000/api/v1/health/live`
- `GET http://127.0.0.1:8000/api/v1/health/ready`
- `GET http://127.0.0.1:8000/docs`

## 前端本地运行

使用 Node.js 24 和 pnpm 11：

```powershell
cd frontend
pnpm install
pnpm dev
```

开发服务器默认访问 `http://127.0.0.1:5173`，并将 `/api` 请求代理到
`http://127.0.0.1:8000`。

## 开发边界

v1 不执行、编译或导入用户代码，不允许 Agent 使用 Shell、外部网络或任意
SQL，也不承诺替代人工审查或成熟 SAST 产品。README 中的实验数据只会来自
可复现 Benchmark。

## License

[Apache License 2.0](LICENSE)
