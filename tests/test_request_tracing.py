import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.logging_config import RequestIdFilter
from app.main import _request_id_from_header
from app.request_context import get_request_id, set_request_id


def test_request_id_accepts_valid_header_and_generates_for_missing_or_invalid():
    assert _request_id_from_header("trace-123") == "trace-123"
    generated = _request_id_from_header(None)
    assert generated != "-"
    assert len(generated) == 36
    assert _request_id_from_header("x\n-y") != "x\n-y"
    assert _request_id_from_header("a" * 129) != "a" * 129


def test_request_id_filter_uses_context():
    token = set_request_id("trace-test")
    try:
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)
        RequestIdFilter().filter(record)
        assert getattr(record, "request_id") == "trace-test"
    finally:
        from app.request_context import reset_request_id
        reset_request_id(token)
    assert get_request_id() == "-"


def test_request_id_is_available_inside_fastapi_request():
    test_app = FastAPI()

    @test_app.get("/trace")
    async def trace():
        return {"request_id": get_request_id()}

    with TestClient(test_app) as client:
        provided = client.get("/trace", headers={"X-Request-ID": "client-trace"})
        generated = client.get("/trace")

    assert provided.json()["request_id"] == "client-trace"
    assert provided.headers["x-request-id"] == "client-trace"
    assert generated.headers["x-request-id"] == generated.json()["request_id"]
    assert generated.json()["request_id"] != "-"
