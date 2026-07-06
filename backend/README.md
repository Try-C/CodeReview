# CodeReview Agent Backend

FastAPI backend for the CodeReview Agent platform.

## Development

Use Python 3.12 from this directory. Start PostgreSQL and Redis first, then copy
`.env.example` to `.env` and adjust the connection URLs for your machine:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python -m pytest
uvicorn app.main:app --reload
```

The current public endpoints are:

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `DELETE /api/v1/projects/{project_id}`
- `GET /docs`

The liveness endpoint does not call external services. Readiness checks both
PostgreSQL and Redis and returns `503 SERVICE_NOT_READY` when either is
unavailable. Authenticated project endpoints always scope access by the current
user. Docker-based local orchestration is intentionally not included.
