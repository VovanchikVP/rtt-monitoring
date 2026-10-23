"""Ручка `POST /players/tours/refresh` — постановка задач на всех игроков.

Задачи до брокера не доходят: `fill_player_tours_task` подменяется записной
книжкой, так что проверяется ровно то, что ручка ставит в очередь.
"""

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

import app as app_module
from src.const import REQUEST_DELAY
from src.models.base import get_session
from src.service import players as players_service

PLAYER_IDS = [101, 102, 103]


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
    """Сессия, отдающая заранее заданный список игроков."""

    def __init__(self, player_ids: list[int]) -> None:
        self.player_ids = player_ids

    async def scalars(self, statement: object) -> list[int]:
        return self.player_ids


@pytest.fixture
def task(monkeypatch):
    fake = FakeTask()
    monkeypatch.setattr(players_service, "fill_player_tours_task", fake)
    return fake


@pytest.fixture
def client(request):
    """Клиент API с подменённой сессией базы."""
    player_ids = getattr(request, "param", PLAYER_IDS)
    app_module.app.dependency_overrides[get_session] = lambda: FakeSession(player_ids)
    with TestClient(app_module.app) as test_client:
        yield test_client
    app_module.app.dependency_overrides.clear()


def test_answers_immediately_with_queue_summary(client, task):
    response = client.post("/players/tours/refresh")

    # работа идёт в фоне, поэтому 202, а не 200
    assert response.status_code == 202
    assert response.json() == {"players": len(PLAYER_IDS), "queued": len(PLAYER_IDS)}


def test_queues_one_task_per_player(client, task):
    client.post("/players/tours/refresh")

    assert [call.args for call in task.calls] == [[player_id] for player_id in PLAYER_IDS]


def test_spreads_tasks_by_request_delay(client, task):
    client.post("/players/tours/refresh")

    assert [call.countdown for call in task.calls] == [0, REQUEST_DELAY, 2 * REQUEST_DELAY]


@pytest.mark.parametrize("client", [[]], indirect=True)
def test_queues_nothing_without_players(client, task):
    response = client.post("/players/tours/refresh")

    assert response.status_code == 202
    assert response.json()["queued"] == 0
    assert task.calls == []


def test_answers_503_when_broker_is_down(client, task):
    task.error = OSError("брокер недоступен")

    response = client.post("/players/tours/refresh")

    # периодической задачи на этот случай нет, молча терять запрос нельзя
    assert response.status_code == 503
    assert "Очередь задач недоступна" in response.json()["detail"]
