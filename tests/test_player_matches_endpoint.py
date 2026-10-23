"""Ручка `GET /players/{id}/matches` — плашки матчей рядом с графиком."""

from dataclasses import dataclass
from datetime import date

import pytest
from fastapi.testclient import TestClient

import app as app_module
from src.models import Players
from src.models.base import get_session
from src.service import PlayersService

PLAYER_ID = 101


@dataclass
class Row:
    """Строка выборки матчей игрока."""

    date: date | None
    opponent: str
    first_player_id: int
    first_score: int | None
    second_score: int | None
    score: str | None
    winner_player_id: int | None


# игрок записан в матче то первым, то вторым — счёт разворачивается по-разному
MATCHES = [
    Row(date(2026, 10, 12), "Петров Пётр Петрович", PLAYER_ID, 2, 1, "6-4 3-6 7-5", PLAYER_ID),
    Row(date(2026, 10, 10), "Сидоров Иван Ильич", 202, 2, 0, "6-3 7-6(5)", 202),
]


class FakeSession:
    """Сессия с одним игроком и заготовленной выборкой матчей."""

    def __init__(self, player: Players | None, rows: list[Row]) -> None:
        self.player = player
        self.rows = rows

    async def get(self, model: type, player_id: int) -> Players | None:
        return self.player

    async def execute(self, statement: object) -> list[Row]:
        return self.rows


@pytest.fixture
def client(request):
    player, rows = getattr(request, "param", ("player", MATCHES))
    session = FakeSession(Players(id=PLAYER_ID) if player else None, rows)
    app_module.app.dependency_overrides[get_session] = lambda: session
    with TestClient(app_module.app) as test_client:
        yield test_client
    app_module.app.dependency_overrides.clear()


def test_score_is_turned_to_the_asked_player(client):
    response = client.get(f"/players/{PLAYER_ID}/matches")

    assert response.status_code == 200
    assert response.json() == [
        {
            "date": "2026-10-12",
            "opponent": "Петров Пётр Петрович",
            "sets": "2-1",
            "games": "6-4 3-6 7-5",
            "won": True,
        },
        # игрок шёл в матче вторым: и сеты, и геймы развёрнуты, тай-брейк на месте
        {
            "date": "2026-10-10",
            "opponent": "Сидоров Иван Ильич",
            "sets": "0-2",
            "games": "3-6 6-7(5)",
            "won": False,
        },
    ]


@pytest.mark.parametrize(
    "client",
    [("player", [Row(None, "Петров Пётр Петрович", PLAYER_ID, None, None, None, None)])],
    indirect=True,
)
def test_unplayed_match_keeps_empty_fields(client):
    response = client.get(f"/players/{PLAYER_ID}/matches")

    assert response.status_code == 200
    assert response.json() == [
        {
            "date": None,
            "opponent": "Петров Пётр Петрович",
            "sets": None,
            "games": None,
            "won": None,
        }
    ]


@pytest.mark.parametrize("client", [("player", [])], indirect=True)
def test_player_without_matches_gets_empty_list(client):
    response = client.get(f"/players/{PLAYER_ID}/matches")

    # фронт покажет «матчей пока нет», а не ошибку
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("client", [(None, [])], indirect=True)
def test_unknown_player_gets_404(client):
    response = client.get("/players/999/matches")

    assert response.status_code == 404
    assert "не найден" in response.json()["detail"]


@pytest.mark.parametrize("limit", ["0", "51", "два"])
def test_bad_limit_is_rejected(client, limit):
    response = client.get(f"/players/{PLAYER_ID}/matches", params={"limit": limit})

    assert response.status_code == 422


# ---- разделитель сетов ----

# в сетке турнира счёт приходит через запятую, в расписании — через пробел;
# наружу он должен выглядеть одинаково


@pytest.mark.parametrize(
    ("stored", "expected"),
    [("2-6,1-6", "2-6 1-6"), ("2-6 1-6", "2-6 1-6"), ("6-4, 3-6, 7-5", "6-4 3-6 7-5")],
)
def test_sets_are_always_separated_by_space(stored, expected):
    row = Row(date(2026, 10, 12), "Петров Пётр Петрович", PLAYER_ID, 2, 1, stored, PLAYER_ID)
    assert PlayersService.as_player_match(row, PLAYER_ID).games == expected


def test_comma_separated_score_is_flipped_for_the_second_player():
    row = Row(date(2026, 10, 12), "Петров Пётр Петрович", 202, 2, 0, "6-0,7-6(5)", 202)
    match = PlayersService.as_player_match(row, PLAYER_ID)
    assert match.games == "0-6 6-7(5)"
    assert match.sets == "0-2"
