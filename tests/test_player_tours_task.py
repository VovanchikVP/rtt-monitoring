"""Задача `tours.fill_player` — обновление сыгранных турниров одного игрока.

Запросы уходят в поддельный API, запись в базу подменяется: проверяется то,
что задача спрашивает у внешнего API и что передаёт на сохранение.
"""

import json
from datetime import date

import aiohttp
import pytest

from src.celery.service.fill_player_tours import FillPlayerToursService
from src.celery.service.fill_points import FillPointsService
from src.const import REQUEST_DELAY

PLAYER_ID = 48215

TOUR = {
    "tour_id": 305042,
    "name": "Первенство Хабаровского края",
    "city": "Хабаровск",
    "date": "2026-06-01",
    "pos": "25-32",
    "points": 9,
}

SAVED_TOUR = {
    "tour_id": 305042,
    "name": "Первенство Хабаровского края",
    "city": "Хабаровск",
    "date": date(2026, 6, 1),
    "position": "25-32",
    "points": 9,
}


def details(tours: list[dict]) -> str:
    return json.dumps({"data": {"rating.details": {"rating": {"points": 480}, "tours": tours}}})


@pytest.fixture
def saved(monkeypatch):
    """Перехватить запись результатов: базы в тестах нет."""
    calls = []

    async def save(player_id: int, tours: list[dict]) -> int:
        calls.append((player_id, tours))
        return len(tours)

    monkeypatch.setattr(FillPointsService, "save_rating_details", save)
    return calls


async def test_asks_api_for_current_rating_card(api, saved):
    api.always(details([TOUR]))

    await FillPlayerToursService.run(PLAYER_ID)

    request = api.request
    assert request.form["method[0]"] == "rating.details"
    assert request.form["player_id"] == str(PLAYER_ID)
    # рейтинг-лист текущего месяца: в нём турниры последнего года
    assert request.form["rating_id"] == FillPointsService.get_rating_id()


async def test_saves_parsed_tours(api, saved):
    api.always(details([TOUR]))

    assert await FillPlayerToursService.run(PLAYER_ID) == 1
    assert saved == [(PLAYER_ID, [SAVED_TOUR])]


async def test_answer_without_tours_saves_nothing(api, saved):
    api.always(details([]))

    assert await FillPlayerToursService.run(PLAYER_ID) == 0
    assert saved == []


async def test_api_error_is_not_swallowed(api, saved):
    # задача упадёт, celery отметит сбой; молча записать «ноль турниров» нельзя
    api.always(status=500)

    with pytest.raises(aiohttp.ClientResponseError):
        await FillPlayerToursService.run(PLAYER_ID)
    assert saved == []


# ---- постановка задач в очередь ----


class FakeCelery:
    """Приложение celery, которое пишет задачи в список вместо брокера."""

    def __init__(self) -> None:
        self.sent = []

    def send_task(self, name: str, args: list, countdown: int = 0) -> None:
        self.sent.append((name, args, countdown))


@pytest.fixture
def celery(monkeypatch):
    fake = FakeCelery()
    monkeypatch.setattr("src.celery.service.fill_player_tours.celery_app", fake)
    return fake


def test_schedules_one_task_per_player(celery):
    FillPlayerToursService.schedule([101, 102, 103])

    assert celery.sent == [
        ("tours.fill_player", [101], 0),
        ("tours.fill_player", [102], REQUEST_DELAY),
        ("tours.fill_player", [103], 2 * REQUEST_DELAY),
    ]


def test_schedules_nothing_for_empty_list(celery):
    FillPlayerToursService.schedule([])

    assert celery.sent == []
