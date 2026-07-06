# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CodeReview Agent is an explainable, measurable AI code review platform for Java and Python. It parses source code with Tree-sitter, builds a Hybrid RAG index (PostgreSQL full-text + pgvector + RRF), runs a bounded LangGraph workflow (Planner → Review → EvidenceVerify → Critic), and produces reports with file/line-level evidence.

The project is developed in single-subtask increments on feature branches (`feat/module-XX-short-name`), merged to `main` after module acceptance. The canonical spec is [`docs/project-outline.md`](docs/project-outline.md); [`AGENTS.md`](AGENTS.md) defines the repository working agreement.

**Currently completed:** Module 01 (scaffold), Module 02 (auth & projects), Module 03 (secure upload), Module 04 (async task & SSE), Module 05 (scanner), Module 06 (multilingual parsing), Module 07 (indexing), Module 08 (Hybrid RAG). Module 09 (Benchmark) is next.

## Repository structure

```
backend/               Python 3.12, FastAPI, SQLAlchemy 2 (async), Celery + Redis
  app/main.py          App factory: create_app(settings, runtime) → FastAPI
  app/api/             Route handlers (health, auth, uploads, projects, reviews)
  app/core/            config, database, redis, security, exceptions, runtime, logging, middleware
  app/models/          SQLAlchemy ORM: User, Project, ProjectFile, UploadSession, ReviewTask, TaskEvent,
                       CodeChunk, CodeSymbol, CodeRelation, RetrievalRecord
  app/schemas/         Pydantic request/response models (auth, common, health, project, task, upload)
  app/services/        Business logic: auth_service, project_service, upload_service, progress_service, task_service, upload_policy
  app/storage/         LocalProjectStorage (isolated upload directories with random storage_key)
  app/scanner/         FileScanner, FileFilter, PriorityClassifier → scan reports
  app/languages/       LanguageAdapter base + TreeSitterLanguageAdapter + Java/Python adapters
  app/indexing/        EmbeddingProvider, IndexingService, DashScope adapter, HNSW options, text utils
  app/retrieval/       VectorSearcher, KeywordSearcher, RRF fusion, HybridRetriever, ContextAssembler
  app/tasks/           Celery app + review pipeline task (outer lifecycle, runs async and reports progress)
  alembic/             Database migrations (6 versions through M08 retrieval_records)
  tests/unit/          Unit tests (config, logging, security, parser contract, scanner, indexing, retrieval)
  tests/integration/   Integration tests (health, auth, uploads, reviews, scanning, indexing, retrieval, migrations)
  tests/conftest.py    Fixtures: test_settings (app_env=test), fake runtime deps, TestClient
  tests/fakes.py       FakeHealthDependency, FakeTaskDispatcher, FakeTaskEventBus, FakeEmbeddingProvider
frontend/              Vue 3, TypeScript, Pinia, Element Plus, Vite 8, Vitest
  src/api/             HTTP client + per-module API wrappers
  src/stores/          Pinia stores (health)
  src/views/           Page components (HomeView)
  src/router/          Vue Router (currently single-route)
  src/types/           Shared TypeScript types
docs/                  project-outline.md (full architecture spec)
```

## Key architectural patterns

### App factory with explicit runtime injection
`create_app(settings, runtime)` builds FastAPI with explicit dependencies. Tests inject `FakeHealthDependency` instances instead of real PostgreSQL/Redis. The `RuntimeContext` dataclass owns all process-wide dependencies (database, redis, storage, task_dispatcher, event_bus) and manages their lifecycle.

### Typed, frozen configuration
All settings in `app/core/config.py` use Pydantic `BaseSettings` with `frozen=True`. Production safety is enforced via `model_validator` (no debug, no wildcard CORS, strong JWT secret). Use `@lru_cache` `get_settings()` to access — never instantiate `Settings()` directly outside the factory.

### Unified error handling
`AppError` (code, message, status_code, details, headers) is raised by services and rendered as `ErrorResponse` by registered handlers. All API responses use the same envelope: `{code, message, request_id, details}`.

### HealthDependency protocol
External services (database, redis) implement `HealthDependency`: `name`, `check()`, `close()`. The `/ready` endpoint checks all deps concurrently with independent timeouts. Fake implementations record calls for test assertions.

### Task/SSE event source of truth
`task_events.id` (PostgreSQL autoincrement) is the canonical event ID. Redis Stream carries the same ID for real-time delivery only. SSE `Last-Event-ID` recovery queries `task_events WHERE id > last_id` — Redis is best-effort, never the primary event store.

### Idempotency through uniqueness
Every write path has a DB-level unique constraint: `(user_id, idempotency_key)` on tasks, `(project_id, chunk_fingerprint)` on chunks, `(task_id, fingerprint)` on issues, `(task_id, run_key)` on node runs.

### Test fakes, not mocks
`tests/fakes.py` provides deterministic `FakeHealthDependency`, `FakeTaskDispatcher`, `FakeTaskEventBus`, `FakeEmbeddingProvider`. Tests never call paid model APIs. Integration tests use SQLite (aiosqlite) and test the actual FastAPI app through `TestClient`.

### LanguageAdapter pattern
`LanguageAdapter` (ABC) defines `detect()`, `parse()`, `risk_hints()`, `normalize_query()`. `TreeSitterLanguageAdapter` implements shared Tree-sitter parsing, chunk splitting, fingerprint hashing, and fallback. `JavaLanguageAdapter` and `PythonLanguageAdapter` only override language-specific queries (symbol types, signatures, imports, references). Use `LanguageAdapterRegistry.resolve(file_path, content)` to get the right adapter.

### Hybrid RAG retrieval
`HybridRetriever` embeds the query once (text_type=query, one retry on failure), runs vector search (pgvector cosine with HNSW) and keyword search (PostgreSQL tsvector/tsquery with SQLite LIKE fallback) in parallel, fuses rankings via RRF (`1/(k+rank)`), persists idempotent trace to `retrieval_records`, and returns scored chunks. Degradation chain per spec §11.4: Embedding failure → keyword-only; Vector failure → keyword → ILIKE symbol name match as last resort; both failures → empty result with degradation markers. `ContextAssembler` enriches chunks with symbols, outbound relations, and target symbols via batch queries, then applies Token Budget truncation.

### Embedding provider boundary
`EmbeddingProvider` is a Protocol with `model`, `dimension`, and `embed(texts, text_type)`. `DashScopeEmbeddingProvider` calls the Alibaba Cloud native endpoint. Chunks use `text_type=document`; queries use `text_type=query`. Failures are caught and recorded as `embedding_error` with `keyword_only` degradation — never silent truncation.

## Commands

### Backend (run from `backend/`)

```bash
# Install
python -m pip install -e ".[dev]"

# Run database migrations
python -m alembic upgrade head

# Create a new migration (replace "description")
python -m alembic revision --autogenerate -m "description"

# Lint
python -m ruff check .

# Format check
python -m ruff format --check .

# Type check
python -m mypy app tests

# Run all tests (with coverage, must pass ≥85%)
python -m pytest

# Run a single test file
python -m pytest tests/unit/test_security.py

# Run a single test
python -m pytest tests/unit/test_security.py::test_function_name -v

# Start dev server (requires PostgreSQL + Redis)
uvicorn app.main:app --reload
```

### Frontend (run from `frontend/`)

```bash
# Install
pnpm install --frozen-lockfile

# Dev server (http://127.0.0.1:5173, proxies /api → 127.0.0.1:8000)
pnpm dev

# Complete verification (lint + format + typecheck + test + build)
pnpm run check

# Individual steps
pnpm run lint          # ESLint (max-warnings=0)
pnpm run format:check  # Prettier
pnpm run typecheck     # vue-tsc
pnpm test              # Vitest
pnpm run build         # Vite production build
```

### Repository-level checks

```bash
git diff --check
git status --short
```

## Development workflow

1. Confirm the current module and one bounded objective
2. Inspect existing code — preserve unrelated changes
3. Implement the smallest complete behavior
4. Add/update tests and docs in the same subtask
5. Run relevant tests and static checks before committing
6. Use Conventional Commits: `feat(scope):`, `fix(scope):`, `test(scope):`, `chore(scope):`, `docs(scope):`
7. Commit and push to the module branch; stop and report — don't start next subtask without request

## Technology constraints

- Python 3.12 only; Node.js 24 with pnpm 11
- All database changes require an Alembic migration
- All LLM outputs must pass Pydantic validation
- External dependencies injected through constructors or `RuntimeContext` — never via module-level imports or globals
- Long-running work must not block HTTP requests (delegate to Celery)
- Task writes must account for retries, transactions, and idempotency
- Never execute, import, or compile uploaded user code
- Automated tests use fake providers — never make paid API calls
- API keys belong only in `.env`; never in source, fixtures, logs, or error responses
- Cost calculations use `Decimal`, never binary floats
- Model pricing comes from config; every call saves a pricing snapshot; supplier prices are never hardcoded
- Vector search and keyword search both degrade gracefully on SQLite (used in CI/tests)

## Planned but not yet built (P0 scope)

The following are specified in `docs/project-outline.md` but not yet implemented:
- `app/llm/` — LLM provider adapter (DeepSeek) with usage tracking and cost calculation
- `app/agents/` — Planner, Reviewer, Critic agent nodes
- `app/graph/` — LangGraph state machine (nodes, routes, BudgetGuard)
- `app/reporting/` — Report generation service and templates
- `benchmark/` — Ground truth datasets, metrics, ablation experiments
- `app/evaluation/` — Evaluation runner and metrics
- Modules 09–12 as defined in the project outline
