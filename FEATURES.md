# FastAPI Blog — Feature Guide

A production-style blog backend built with FastAPI: JWT auth with RBAC, async SQLAlchemy + PostgreSQL, Redis caching, server-rendered Jinja2 templates, structured logging, and a ~2,100-line pytest suite. This guide covers what's implemented and how to run/use each piece.

Verified 2026-07-26: full test suite (142 tests) passing, live server smoke-tested against real Postgres + Redis, all 10 templates exercised end-to-end in a browser (register → login → create/edit/delete post → account settings → password reset pages → 404 page).

---

## 1. Architecture

Layered design, each layer only talks to the one below it:

```
routes (app/api/routes)     → HTTP in/out, status codes, request validation
  ↓
services (app/services)     → business logic, orchestration, cache reads/writes
  ↓
repositories (app/repositories) → SQL queries, no business logic
  ↓
models (app/models)         → SQLAlchemy ORM
```

Supporting layers: `app/core` (config, security, logging, rate limiting), `app/infrastructure/cache` (Redis), `app/exceptions` (typed errors → HTTP responses), `app/storage` (file upload abstraction), `app/middleware` (request context).

---

## 2. Running the project

**Prerequisites:** PostgreSQL running, Redis running, `.env` configured (see `.env.example`).

```bash
# install deps
source .venv/bin/activate
pip install -r requirements.txt

# apply migrations
alembic upgrade head

# run the dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Visit `http://localhost:8000` for the site, `http://localhost:8000/docs` for interactive Swagger UI (auto-generated from the Pydantic schemas).

**Run tests:**
```bash
pytest                          # full suite with coverage report
pytest app/tests/test_auth.py   # single file
pytest -k "test_create_post"    # by name
```
Tests use a separate `test_blog` Postgres database (set in `app/tests/conftest.py`), mocked Redis (`fakeredis`), and mocked S3/email — no external services required to run them, but a real Postgres instance is needed for the `test_blog` DB.

---

## 3. Authentication & Authorization

**Mechanism:** JWT access + refresh tokens (`app/core/security.py`, `app/services/auth_service.py`).

| Flow | Endpoint | Notes |
|---|---|---|
| Register | `POST /api/v1/users` | Creates user, auto-assigns `author` role, sends verification email, rate-limited 5/hour |
| Login | `POST /api/v1/users/token` | OAuth2 password form (`username` field = **email**, not username). Blocked until email is verified. Rate-limited 5/min |
| Refresh | `POST /api/v1/users/refresh` | Exchanges refresh token for new access token. Rate-limited 10/min |
| Logout | `POST /api/v1/users/logout` | Revokes the refresh token server-side |
| Verify email | `POST /api/v1/users/verify-email` | Token sent via email, 24h TTL |
| Forgot password | `POST /api/v1/users/forgot-password` | Sends reset link, rate-limited 3/hour, doesn't reveal if the email exists |
| Reset password | `POST /api/v1/users/reset-password` | Token TTL 60 min |
| Change password | `PATCH /api/v1/users/me/password` | Requires current password, authenticated |
| Google OAuth | `POST /api/v1/users/oauth/google` | Verifies Google ID token, creates/links account by email |

**Passwords:** Argon2 via `pwdlib`. **Tokens:** HS256 JWT, access token 15 min, refresh token 30 days (both configurable in `.env`). Reset/verification tokens are random 32-byte values, stored **hashed** (SHA-256) — the raw token only ever exists in the emailed link, never in the database.

**RBAC:** `Role` ↔ `Permission` many-to-many (`app/models/role.py`). Every new user gets the `author` role (`posts:create`). An `admin` role additionally has `posts:update` / `posts:delete` on any post. Regular authors can only edit/delete their **own** posts — enforced in `app/services/post_service.py`, verified by a live 403 test against another user's post.

Use it: send `Authorization: Bearer <access_token>` on protected endpoints. In the browser UI, tokens live in `localStorage` (`app/static/js/auth.js`) and are attached automatically by each page's fetch calls.

---

## 4. Posts API

`app/api/routes/posts.py`, prefix `/api/v1/posts`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` | public | List posts — pagination (`skip`, `limit`), full-text `search`, `author` filter, `created_after`/`created_before` date range, `sort` (date/title/likes) + `order` (asc/desc) |
| POST | `/` | `posts:create` | Create a post |
| GET | `/{id}` | public | Get one post |
| PUT | `/{id}` | author-only | Full replace |
| PATCH | `/{id}` | author-only | Partial update |
| DELETE | `/{id}` | author-only | Delete (204) |

Example:
```bash
curl "http://localhost:8000/api/v1/posts?search=FastAPI&sort=likes&order=desc&limit=5"
```

---

## 5. Users API

`app/api/routes/users.py`, prefix `/api/v1/users`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/{id}` | Public profile |
| PATCH | `/{id}` | Update own username/email |
| DELETE | `/{id}` | Delete own account (cascades to posts and tokens) |
| GET | `/{id}/posts` | Paginated list of a user's posts |
| PATCH | `/{id}/picture` | Upload profile picture (≤5MB, JPEG/PNG/GIF/WebP) |
| DELETE | `/{id}/picture` | Reset to default avatar |

---

## 6. Caching (Redis, cache-aside pattern)

`app/infrastructure/cache/`. Post list and post detail reads are cached; any create/update/delete invalidates the relevant keys.

- `posts:list:<hash of query params>` — TTL from `cache_default_ttl` (default 300s)
- `posts:<id>` — post detail
- Writes call `delete_pattern("posts:list:*")` and `delete(f"posts:{id}")` to keep cache and DB consistent — confirmed live: a write immediately clears stale list entries.

Every cache operation logs a structured JSON line (`cache_key`, `cache_result`: hit/miss/error) — useful for tuning TTLs or debugging staleness.

Swap the backend by implementing `app/services/cache_service.py`'s `CacheService` interface — `RedisCacheService` is the only implementation today.

---

## 7. Observability

- **Structured JSON logging** (`app/core/logging.py`): every log line includes `timestamp`, `level`, `request_id`, and contextual extras (`path`, `method`, `status_code`, `duration_ms`, `user_id`, cache fields).
- **Request ID propagation** (`app/middleware/request_context.py`): every request gets a UUID, threaded through `contextvars`, so all logs for one request share an ID — grep your logs by `request_id` to trace a single call end-to-end.
- **Audit log** (`app/services/audit_service.py` → `audit_logs` table): records who did what (register, login, logout, password reset, post/user create/update/delete) with method, path, and IP — a persisted trail independent of the log files.
- **Rate limiting** (`app/core/rate_limit.py`, SlowAPI + Redis): per-route limits on auth endpoints to blunt brute-force/spam.
- `sentry-sdk` is in `requirements.txt` but not wired into `main.py` — add a `sentry_sdk.init()` call in the lifespan if you want error tracking in production.

---

## 8. Server-rendered pages (Jinja2)

`app/templates/`, wired via `Jinja2Templates` in `app/main.py`. Not an SPA — plain HTML pages with vanilla JS (`fetch` + Bootstrap modals) hitting the JSON API underneath. All ten pages below were manually driven through a full user journey (register → verify → login → CRUD a post → edit profile → delete account) with zero console errors.

| Route | Template | Notes |
|---|---|---|
| `GET /` , `GET /posts` | `home.html` | Post feed, "Load More Posts" does incremental fetch (no full reload) |
| `GET /posts/{id}` | `post.html` | Post detail; Edit/Delete buttons appear only for the post's author |
| `GET /users/{id}/posts` | `user_posts.html` | One user's posts, paginated |
| `GET /login` | `login.html` | Email+password form, optional Google Sign-In button if `GOOGLE_CLIENT_ID` is set |
| `GET /register` | `register.html` | |
| `GET /account` | `account.html` | Profile edit, picture upload, password change, logout, delete account |
| `GET /forgot-password` | `forgot_password.html` | |
| `GET /reset-password?token=...` | `reset_password.html` | |
| any 4xx/error | `error.html` | Shared error page (API routes under `/api` still get JSON, not HTML) |

**UX pattern to know:** after a mutating action (login, register, edit, delete), a Bootstrap "Success" modal appears; the page only redirects/reloads once you **close that modal** (`hidden.bs.modal` listener) — it's not stuck, that's the intended flow.

**Login field gotcha:** the login form's "Email" field maps to the OAuth2 `username` parameter — the backend always authenticates by email, never by username.

---

## 9. Configuration reference

All settings in `app/core/config.py`, loaded from `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — (required) | `postgresql+psycopg://user:pass@host/db` |
| `SECRET_KEY` | — (required) | JWT signing key |
| `REDIS_URL` | `redis://localhost:6379/0` | Cache + rate-limiter backend |
| `CACHE_DEFAULT_TTL` | 300 | Seconds |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 15 | |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 30 | |
| `RESET_TOKEN_EXPIRE_MINUTES` | 60 | |
| `EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS` | 24 | |
| `MAX_UPLOAD_SIZE_BYTES` | 5242880 | Profile picture cap |
| `POSTS_PER_PAGE` | 10 | Default pagination size |
| `MAIL_SERVER` / `MAIL_PORT` / `MAIL_USERNAME` / `MAIL_PASSWORD` / `MAIL_FROM` / `MAIL_USE_TLS` | — | SMTP for verification/reset emails |
| `FRONTEND_URL` | `http://localhost:8000` | Used to build links in emails |
| `GOOGLE_CLIENT_ID` | "" | Enables Google Sign-In button when set |
| `LOG_LEVEL` | INFO | |

---

## 10. Test suite

`app/tests/`, 142 tests, run with `pytest`. `pytest.ini` also generates an HTML coverage report in `htmlcov/`.

| File | Covers |
|---|---|
| `test_auth.py` | Register, login, refresh, logout, password reset, email verify, Google OAuth, RBAC permissions |
| `test_posts.py` | CRUD, search/filter/sort, pagination, ownership checks |
| `test_services.py` | Service-layer business logic |
| `test_repositories.py` | Query correctness (search, filter, sort) |
| `test_cache.py` | Cache-aside get/set/delete, serialization |
| `test_api.py` | Contract/response-shape tests |
| `test_observability.py` | Audit logging, request ID propagation, log format |
| `test_performance.py` | Benchmark (`pytest-benchmark`) for cache-key generation |
| `test_failures.py` | Invalid JWT, missing permissions, 404s, validation errors, SMTP failures |

Fixtures (`conftest.py`) spin up an isolated `test_blog` Postgres DB with per-test transaction rollback, mock Redis (`fakeredis`), mock S3 (`moto`), and no-op email sending — so the suite has no external side effects.

---

## 11. Known gaps (not bugs, just not built)

- No Prometheus/Grafana metrics — only structured logs + the audit table.
- Sentry dependency present but not initialized.
- Minor a11y lint notices (missing `autocomplete` attributes on password fields) — cosmetic, doesn't affect function.
