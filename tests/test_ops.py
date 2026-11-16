import json
import logging

import pytest

from core.logging import JsonFormatter, RequestIdFilter
from core.request_id import reset_request_id, set_request_id

pytestmark = pytest.mark.django_db


def test_health_needs_no_auth(api_client):
    response = api_client.get("/api/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_checks_database_and_cache(api_client):
    response = api_client.get("/api/ready/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "cache": "ok"}}


def test_ready_is_503_when_a_dependency_is_down(api_client, monkeypatch):
    def broken():
        raise ConnectionError("redis is down")

    monkeypatch.setattr("core.views.ReadyView.cache", staticmethod(broken))
    response = api_client.get("/api/ready/")
    assert response.status_code == 503
    assert response.json()["checks"]["cache"] == "error"


def test_every_response_has_a_request_id(api_client):
    generated = api_client.get("/api/health/")["X-Request-ID"]
    assert len(generated) == 32

    echoed = api_client.get("/api/health/", HTTP_X_REQUEST_ID="lb-123")["X-Request-ID"]
    assert echoed == "lb-123"

    # Junk from the outside is replaced, not logged.
    replaced = api_client.get("/api/health/", HTTP_X_REQUEST_ID="bad id\nwith newline")["X-Request-ID"]
    assert replaced != "bad id\nwith newline" and len(replaced) == 32


def test_json_log_lines_include_request_id_and_extra_fields():
    record = logging.LogRecord("callflow.access", logging.INFO, __file__, 1, "request", (), None)
    record.status = 200
    record.org = "acme"
    token = set_request_id("abc123")
    try:
        RequestIdFilter().filter(record)
    finally:
        reset_request_id(token)

    line = json.loads(JsonFormatter().format(record))

    assert line["message"] == "request"
    assert line["request_id"] == "abc123"
    assert line["status"] == 200 and line["org"] == "acme"
    assert line["level"] == "INFO"


def test_openapi_schema_and_docs_are_served(api_client):
    schema = api_client.get("/api/schema/", HTTP_ACCEPT="application/json")
    assert schema.status_code == 200
    body = schema.json()
    assert "/api/webhooks/calls/" in body["paths"]
    assert {"ApiKey", "jwtAuth"} <= set(body["components"]["securitySchemes"])
    assert api_client.get("/api/docs/").status_code == 200
