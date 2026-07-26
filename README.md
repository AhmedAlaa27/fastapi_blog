# FastAPI Blog

Production-style blog backend: JWT auth with RBAC, async SQLAlchemy + PostgreSQL, Redis caching, server-rendered Jinja2 templates, structured JSON logging, and a ~2,100-line pytest suite.

Started as a tutorial CRUD app, rebuilt into a layered architecture (routes → services → repositories → models) to demonstrate production patterns: cache-aside caching, RBAC, audit logging, rate limiting, and full test coverage.

## Stack

- **API**: FastAPI, Pydantic v2
- **DB**: PostgreSQL, SQLAlchemy 2.0 (async), Alembic migrations
- **Cache**: Redis (cache-aside pattern)
- **Auth**: JWT (access + refresh), Argon2 password hashing, Google OAuth, RBAC
- **Templates**: Jinja2 + Bootstrap (server-rendered, vanilla JS)
- **Testing**: pytest, pytest-cov, pytest-benchmark, factory-boy, fakeredis, moto

## Quickstart

```bash
# prerequisites: PostgreSQL and Redis running, .env configured (see .env.example)

source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Site: http://localhost:8000
- API docs (Swagger): http://localhost:8000/docs

Run tests:
```bash
pytest
```

## Project layout

```
app/
├── api/routes/      HTTP endpoints (auth, posts, users)
├── services/         business logic
├── repositories/      SQL queries
├── models/            SQLAlchemy ORM
├── schemas/            Pydantic request/response models
├── core/               config, security, logging, rate limiting
├── infrastructure/cache/  Redis cache service
├── middleware/          request context / request ID
├── exceptions/           typed exceptions → HTTP responses
├── templates/            server-rendered Jinja2 pages
├── tests/                pytest suite
└── main.py               app entrypoint
```

## Documentation

Full feature guide, API reference, RBAC model, caching details, and template inventory: [FEATURES.md](FEATURES.md).
