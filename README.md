# CodeReview Agent

面向 Java、Python 项目的可解释、可评测 AI 代码审查平台。

项目计划通过 Tree-sitter 建立带文件路径、符号和行号的代码知识库，使用
PostgreSQL 全文检索、pgvector 与 RRF 组成 Hybrid RAG，再通过有界
LangGraph 工作流生成并校验证据充分的审查报告。

## 当前状态

当前处于 **Module 01：工程脚手架**。开发采用单子任务验收制，不提前创建
未使用的模块或声称尚未测得的效果。

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

## 开发边界

v1 不执行、编译或导入用户代码，不允许 Agent 使用 Shell、外部网络或任意
SQL，也不承诺替代人工审查或成熟 SAST 产品。README 中的实验数据只会来自
可复现 Benchmark。

## License

[Apache License 2.0](LICENSE)
