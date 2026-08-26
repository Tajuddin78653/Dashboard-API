# TradeDash API

FastAPI backend for the Trading Dashboard — JWT auth, webhook signal ingestion, trade tracking, APScheduler market monitor, and analytics.

## Requirements

- Python 3.11+
- PostgreSQL (Supabase or local)
- Redis (Upstash or local) — optional for caching

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your `DATABASE_URL`, `JWT_SECRET_KEY`, bot tokens, and any other required values.

### 3. Run database migrations

```bash
alembic upgrade head
```

> **Note:** Alembic uses a synchronous `psycopg2` connection for migrations. Install it with:
> ```bash
> pip install psycopg2-binary
> ```

### 4. Start the development server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

## Deployment (Heroku / Railway / Render)

The `Procfile` is pre-configured:

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set all environment variables from `.env.example` in your hosting platform's dashboard.

## Project Structure

```
app/
├── main.py          # FastAPI app entry point
├── config.py        # Pydantic-settings configuration
├── database.py      # Async SQLAlchemy engine & session
├── models/          # SQLAlchemy ORM models
├── schemas/         # Pydantic request/response schemas
├── routers/         # API route handlers
├── services/        # Business logic
├── core/            # Auth utilities, security
└── utils/           # Helpers
alembic/             # Database migration scripts
```

## Health Check

```
GET /health
→ {"status": "ok", "service": "TradeDash API"}
```
