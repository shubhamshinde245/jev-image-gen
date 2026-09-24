# Backend

FastAPI service using TypeSafe system_one for ticket analysis.

## Setup

```bash
cd backend
uv sync
cp .env.example .env.local   # then set TYPESAFE_API_KEY
```

## Run

```bash
uv run uvicorn main:app --reload
```

- Health: http://127.0.0.1:8000/health
- Docs: http://127.0.0.1:8000/docs
- Analyze: `POST /analyze` with `{"document": "..."}`
