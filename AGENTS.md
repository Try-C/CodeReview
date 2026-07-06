# Repository Working Agreement

## Project goal

Build the P0 scope of CodeReview Agent: an explainable and measurable Java/Python
code-review platform. P1 and P2 work stays out of scope until P0 is accepted.

The canonical product and architecture specification is
[`docs/project-outline.md`](docs/project-outline.md).

## Development cadence

- Implement exactly one clearly bounded subtask per collaboration round.
- Prefer a runnable vertical slice over speculative directories or empty abstractions.
- Add or update tests in the same subtask as the behavior.
- Stop after reporting the changed behavior and verification evidence.
- Do not begin the next subtask without a new user request.

## Git workflow

- Develop a module on `feat/module-XX-short-name`.
- Use Conventional Commits written in English.
- Commit and push every completed, verified subtask to its module branch.
- Merge a module into `main` only after its module-level acceptance checks pass.
- Preserve unrelated user changes and never rewrite shared history.

## Engineering constraints

- Backend runtime: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.
- Frontend runtime: Vue 3, TypeScript, Pinia, Element Plus, pnpm.
- Database changes require an Alembic migration.
- External dependencies must be injected through constructors or runtime context.
- Every API must define request, response, and error schemas.
- Every LLM output must pass Pydantic validation.
- LangGraph routes must be pure functions.
- Long-running work must not block an HTTP request.
- Task writes must account for retries, transactions, and idempotency.
- Never execute, import, or compile uploaded user code.

## Model boundaries

- Generation uses a dedicated `LLMProvider`; development targets
  `deepseek-v4-flash` and formal benchmarks target `deepseek-v4-pro`.
- Embedding uses a separate `EmbeddingProvider` backed by Alibaba Cloud Model
  Studio `text-embedding-v4`, dense output, and 1024 dimensions.
- Chunk indexing uses `text_type=document`; retrieval queries use
  `text_type=query`.
- Automated tests use fake providers and must not make paid API calls.
- API keys belong only in ignored environment files and must never appear in
  source, fixtures, logs, traces, or error responses.

## Verification

Run the narrowest relevant tests and static checks after every subtask. As
tooling is introduced, keep the exact commands in `CONTRIBUTING.md` current.
