"""Access-лог API: строка на запрос вместе со временем его выполнения."""

import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware import describe, log_requests

# «… → 200 за 12.4 мс»
LINE = re.compile(r"^(?P<head>.+?) → (?P<status>\d+|ошибка) за (?P<ms>[\d.]+) мс$")


@pytest.fixture
def client():
    app = FastAPI()
    app.middleware("http")(log_requests)

    @app.get("/ok")
    async def ok() -> dict:
        return {"status": "ok"}

    @app.get("/boom")
    async def boom() -> dict:
        raise RuntimeError("обработчик упал")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def log(caplog):
    """Записи access-лога; читать после запроса, список пополняется по ходу."""
    caplog.set_level(logging.INFO, logger="api.access")
    return caplog


def parsed(log) -> re.Match:
    records = log.records
    assert len(records) == 1, f"записей в логе: {len(records)}"
    match = LINE.match(records[0].getMessage())
    assert match is not None, records[0].getMessage()
    return match


def test_request_is_logged_once_with_duration(client, log):
    client.get("/ok")

    match = parsed(log)
    assert match["status"] == "200"
    assert float(match["ms"]) >= 0


def test_line_carries_client_method_and_path(client, log):
    client.get("/ok")

    assert parsed(log)["head"].endswith("GET /ok")


def test_query_string_is_kept(client, log):
    client.get("/ok", params={"limit": 10, "offset": 20})

    # по строке запроса видно, какую именно страницу просили
    assert parsed(log)["head"].endswith("GET /ok?limit=10&offset=20")


def test_failed_request_is_logged_too(client, log):
    # иначе упавший запрос просто исчез бы из лога
    client.get("/boom")

    match = parsed(log)
    assert match["status"] == "ошибка"
    assert log.records[0].levelno == logging.ERROR
    assert log.records[0].exc_info is not None


def test_error_status_is_logged_as_is(client, log):
    client.get("/нет-такого")

    assert parsed(log)["status"] == "404"


# ---- описание запроса ----


class FakeUrl:
    def __init__(self, path: str, query: str) -> None:
        self.path = path
        self.query = query


class FakeRequest:
    def __init__(self, client: object, path: str = "/tours", query: str = "") -> None:
        self.client = client
        self.method = "GET"
        self.url = FakeUrl(path, query)


class FakeClient:
    host = "10.0.0.1"


def test_describe_puts_client_first():
    assert describe(FakeRequest(FakeClient())) == "10.0.0.1 GET /tours"


def test_request_without_client_is_marked_with_dash():
    # клиента может не быть, например у внутреннего вызова
    assert describe(FakeRequest(None)) == "- GET /tours"
