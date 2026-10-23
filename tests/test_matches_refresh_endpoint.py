"""Ручка `POST /tours/matches/refresh` — постановка задач на все турниры.

Задачи до брокера не доходят: `fill_matches_task` подменяется записной
книжкой, так что проверяется ровно то, что ручка ставит в очередь.
"""

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

import app as app_module
from src.const import REQUEST_DELAY
from src.models.base import get_session
from src.service import tours as tours_service

TOUR_IDS = [305042, 305043, 305044]


@dataclass
class Scheduled:
    """Вызов `apply_async` у задачи."""

    args: list
    countdown: int


@dataclass
class FakeTask:
    """Задача, которая вместо брокера пишет вызовы в список."""

    calls: list[Scheduled] = field(default_factory=list)
    error: Exception | None = None

    def apply_async(self, args: list, countdown: int = 0, **_: object) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append(Scheduled(args=args, countdown=countdown))


class FakeSession:
    """Сессия, отдающая заранее заданный список турниров."""

    def __init__(self, tour_ids: list[int]) -> None:
        self.tour_ids = tour_ids

    async def scalars(self, statement: object) -> list[int]:
        return self.tour_ids


@pytest.fixture
def task(monkeypatch):
    fake = FakeTask()
    monkeypatch.setattr(tours_service, "fill_matches_task", fake)
    return fake


@pytest.fixture
def client(request):
    """Клиент API с подменённой сессией базы."""
    tour_ids = getattr(request, "param", TOUR_IDS)
    app_module.app.dependency_overrides[get_session] = lambda: FakeSession(tour_ids)
    with TestClient(app_module.app) as test_client:
        yield test_client
    app_module.app.dependency_overrides.clear()


def test_answers_immediately_with_queue_summary(client, task):
    response = client.post("/tours/matches/refresh")

    # работа идёт в фоне, поэтому 202, а не 200
    assert response.status_code == 202
    assert response.json() == {"tours": len(TOUR_IDS), "queued": len(TOUR_IDS)}


def test_queues_one_task_per_tour(client, task):
    client.post("/tours/matches/refresh")

    assert [call.args for call in task.calls] == [[tour_id] for tour_id in TOUR_IDS]


def test_spreads_tasks_by_request_delay(client, task):
    client.post("/tours/matches/refresh")

    assert [call.countdown for call in task.calls] == [0, REQUEST_DELAY, 2 * REQUEST_DELAY]


@pytest.mark.parametrize("client", [[]], indirect=True)
def test_queues_nothing_without_tours(client, task):
    response = client.post("/tours/matches/refresh")

    assert response.status_code == 202
    assert response.json()["queued"] == 0
    assert task.calls == []


def test_answers_503_when_broker_is_down(client, task):
    task.error = OSError("брокер недоступен")

    response = client.post("/tours/matches/refresh")

    # периодической задачи на этот случай нет, молча терять запрос нельзя
    assert response.status_code == 503
    assert "Очередь задач недоступна" in response.json()["detail"]
