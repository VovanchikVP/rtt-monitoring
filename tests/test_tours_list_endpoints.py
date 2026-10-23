"""Ручки списка турниров: `GET /tours` и `GET /tours/finished`.

Главная страница делает два запроса — отслеживаемые турниры целиком
и страницу завершённых вместе с их общим числом.
"""

from dataclasses import dataclass
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

import app as app_module
from src.models.base import get_session
from src.service import ToursService


@dataclass
class Row:
    """Строка выборки списка турниров."""

    id: int
    name: str | None
    location: str | None
    begin_date: date | None
    end_date: date | None
    players_count: int


ROWS = [
    Row(
        305042, "Первенство Хабаровского края", "Хабаровск", date(2026, 6, 1), date(2026, 6, 7), 54
    ),
    Row(306540, "Турнир на призы TENNIS LIFE", "Москва", date(2026, 9, 21), date(2026, 9, 27), 32),
]


class FakeSession:
    """Сессия с заготовленной выборкой и счётчиком."""

    def __init__(self, rows: list[Row], total: int) -> None:
        self.rows = rows
        self.total = total
        self.statements = []

    async def execute(self, statement: object) -> list[Row]:
        self.statements.append(statement)
        return self.rows

    async def scalar(self, statement: object) -> int:
        self.statements.append(statement)
        return self.total


@pytest.fixture
def session(request):
    rows, total = getattr(request, "param", (ROWS, 23))
    return FakeSession(rows, total)


@pytest.fixture
def client(session):
    app_module.app.dependency_overrides[get_session] = lambda: session
    with TestClient(app_module.app) as test_client:
        yield test_client
    app_module.app.dependency_overrides.clear()


def sql(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


# ---- отслеживаемые ----


def test_running_tours_are_returned_as_a_plain_list(client):
    response = client.get("/tours")

    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [305042, 306540]
    assert response.json()[0]["players_count"] == 54


def test_running_query_keeps_unfinished_and_undated(client, session):
    client.get("/tours")

    statement = sql(session.statements[-1])
    # незаполненный турнир дат ещё не знает — он тоже отслеживаемый
    assert "tours.end_date IS NULL OR tours.end_date >=" in statement
    assert "ORDER BY tours.begin_date ASC NULLS LAST, tours.id" in statement


# ---- завершённые ----


def test_finished_page_carries_items_and_total(client):
    response = client.get("/tours/finished")

    assert response.status_code == 200
    body = response.json()
    assert [t["id"] for t in body["items"]] == [305042, 306540]
    assert body["total"] == 23


def test_finished_are_sorted_by_end_date_from_later_to_earlier(client, session):
    client.get("/tours/finished")

    # id вторым ключом: порядок турниров одного дня не должен плавать
    assert "ORDER BY tours.end_date DESC, tours.id DESC" in sql(session.statements[-1])


def test_finished_query_takes_only_tours_already_over(client, session):
    client.get("/tours/finished")

    assert "tours.end_date IS NOT NULL AND tours.end_date <" in sql(session.statements[-1])


def test_page_is_ten_tours_by_default(client, session):
    client.get("/tours/finished")

    statement = session.statements[-1]
    assert statement._limit == 10
    assert statement._offset == 0


def test_limit_and_offset_come_from_the_query(client, session):
    client.get("/tours/finished", params={"limit": 25, "offset": 50})

    statement = session.statements[-1]
    assert statement._limit == 25
    assert statement._offset == 50


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"limit": "десять"}, {"offset": -1}],
)
def test_bad_paging_is_rejected(client, params):
    assert client.get("/tours/finished", params=params).status_code == 422


@pytest.mark.parametrize("session", [([], 0)], indirect=True)
def test_empty_base_gives_zero_total(client):
    response = client.get("/tours/finished")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


# ---- условия отбора ----


def test_running_and_finished_do_not_overlap():
    # турнир попадает ровно в один из двух списков
    running = sql(ToursService.tours_select().where(ToursService.is_running()))
    finished = sql(ToursService.tours_select().where(ToursService.is_finished()))
    assert "end_date IS NULL OR" in running
    assert "end_date IS NOT NULL AND" in finished


def test_finished_does_not_rely_on_the_is_finished_flag():
    # флаг проставляет задача разбора матчей, у необработанных турниров он снят
    assert "is_finished" not in sql(ToursService.tours_select().where(ToursService.is_finished()))


def test_tours_select_counts_players():
    assert "FROM tours_players" in sql(ToursService.tours_select())
