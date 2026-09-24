# Backend

FastAPI service for Jev pixel generation (TypeSafe System One) plus a small `/analyze` demo.

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

## Pixel generation

Start a job (mock = no API calls):

```bash
curl -s -X POST http://127.0.0.1:8000/generate \
  -H 'Content-Type: application/json' \
  -d '{"mock": true, "size": 16, "max_iters": 2, "seed": 1}'
```

Poll status:

```bash
curl -s http://127.0.0.1:8000/generate/{job_id}
```

Download artifacts (`final.png`, `canvas.html`, `quality.json`, `iter_N.png`):

```bash
curl -OJ http://127.0.0.1:8000/generate/{job_id}/artifacts/final.png
```

Live (API key required): omit `mock` or set `"mock": false`. Size must be a power of 2, max 128.

## Tests

Live tests call the TypeSafe API. `TYPESAFE_API_KEY` must be set in `.env.local`.

```bash
uv run pytest
```
