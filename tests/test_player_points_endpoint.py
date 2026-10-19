"""Ручка `GET /players/{id}/points` — история рейтинга для графика на фронте."""

from dataclasses import dataclass
from datetime import date

import pytest
from fastapi.testclient import TestClient

import app as app_module
from src.models import Players
from src.models.base import get_session

HISTORY = [
    (date(2026, 8, 1), 480),
    (date(2026, 9, 1), 500),
    (date(2026, 10, 17), 510),
]


@dataclass
class Row:
    """Строка выборки `select(Points.date, Points.points)`."""

    date: date
    points: int


class FakeSession:
    """Сессия с одним игроком и его историей очков."""

    def __init__(self, player: Players | None, rows: list[Row]) -> None:
        self.player = player
        self.rows = rows

    async def get(self, model: type, player_id: int) -> Players | None:
        return self.player

    async def execute(self, statement: object) -> list[Row]:
        return self.rows


@pytest.fixture
def client(request):
    player, rows = getattr(request, "param", ("player", HISTORY))
    session = FakeSession(
        Players(id=101) if player else None,
        [Row(day, points) for day, points in rows],
    )
    app_module.app.dependency_overrides[get_session] = lambda: session
    with TestClient(app_module.app) as test_client:
        yield test_client
    app_module.app.dependency_overrides.clear()


def test_returns_history_from_old_to_new(client):
    response = client.get("/players/101/points")

    assert response.status_code == 200
    assert response.json() == [
        {"date": "2026-08-01", "points": 480},
        {"date": "2026-09-01", "points": 500},
        {"date": "2026-10-17", "points": 510},
    ]


@pytest.mark.parametrize("client", [("player", [])], indirect=True)
def test_player_without_points_gets_empty_list(client):
    response = client.get("/players/101/points")

    # график на фронте покажет «рейтинг ещё не собран», а не ошибку
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("client", [(None, [])], indirect=True)
def test_unknown_player_gets_404(client):
    response = client.get("/players/999/points")

    assert response.status_code == 404
    assert "не найден" in response.json()["detail"]
