# CodeReview Agent Backend

FastAPI backend for the CodeReview Agent platform.

## Development

Use Python 3.12 from this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
uvicorn app.main:app --reload
```

The initial public endpoints are:

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `GET /docs`
