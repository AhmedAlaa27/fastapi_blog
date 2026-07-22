import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import request_id_ctx
from app.core.logging import JSONFormatter, RequestIdLogFilter
from app.db.session import get_db
from app.main import app

pytestmark = pytest.mark.anyio


# --- Request ID + timing middleware ---


async def test_request_id_generated_when_absent(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-request-id"]


async def test_request_id_preserved_when_provided(client: AsyncClient):
    response = await client.get("/health", headers={"X-Request-ID": "custom-id-123"})
    assert response.headers["x-request-id"] == "custom-id-123"


async def test_response_has_process_time_header(client: AsyncClient):
    response = await client.get("/health")
    assert "x-process-time-ms" in response.headers


async def test_process_time_header_is_numeric(client: AsyncClient):
    response = await client.get("/health")
    assert float(response.headers["x-process-time-ms"]) >= 0


# --- Structured JSON logging ---


def _make_record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request handled",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_valid_json_with_expected_fields():
    payload = json.loads(JSONFormatter().format(_make_record(request_id="abc-123")))
    assert payload["level"] == "INFO"
    assert payload["message"] == "request handled"
    assert payload["request_id"] == "abc-123"


def test_request_id_log_filter_reads_contextvar():
    token = request_id_ctx.set("filter-test-id")
    try:
        record = _make_record()
        RequestIdLogFilter().filter(record)
        assert record.request_id == "filter-test-id"
    finally:
        request_id_ctx.reset(token)


# --- Global exception handling ---


async def test_domain_exception_maps_to_expected_status(client: AsyncClient):
    response = await client.get("/api/v1/posts/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Post not found"}


async def test_validation_error_returns_standardized_response(client: AsyncClient):
    response = await client.post("/api/v1/users", json={"username": "a"})
    assert response.status_code == 422
    assert "detail" in response.json()


async def test_unexpected_exception_returns_500(
    db_session: AsyncSession, mocked_aws, monkeypatch
):
    async def override_get_db():
        yield db_session

    async def boom(db, post_id):
        raise ValueError("boom")

    monkeypatch.setattr("app.services.post_service.get_post", boom)
    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as ac:
            response = await ac.get("/api/v1/posts/1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500


# --- Health / readiness / liveness ---


async def test_health_is_always_ok(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


async def test_live_is_always_ok(client: AsyncClient):
    response = await client.get("/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_ready_when_database_healthy(client: AsyncClient):
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_ready_when_database_unavailable(client: AsyncClient):
    class BrokenSession:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("db down")

    async def override_get_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = await client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
