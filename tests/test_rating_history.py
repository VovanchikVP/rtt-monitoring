"""Запросы `rating.details` за прошлые месяцы — задача `points.fill_history`.

Задача работает по одному игроку: запрашивает только те месяцы, по которым
записей ещё нет, и выдерживает паузу между запросами.
"""

import json
from datetime import date

import pytest

from src.celery.service import fill_rating_history
from src.celery.service.fill_rating_history import FillRatingHistoryService
from src.const import REQUEST_DELAY

PLAYER_ID = 48215
# ссылка на настоящую паузу: фикстура ниже подменяет её на время тестов
ORIGINAL_PAUSE = FillRatingHistoryService.pause
MONTHS = [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]


def rating(points: int | None, tours: list[dict] | None = None) -> str:
    """Ответ `rating.details`; None — игрока в рейтинг-листе нет."""
    details: dict = {"rating": {"points": points}} if points is not None else {}
    if tours is not None:
        details["tours"] = tours
    return json.dumps({"data": {"rating.details": details}})


def tour(tour_id: int, points: int, pos: str = "5-8") -> dict:
    """Запись турнира в списке `tours`."""
    return {
        "tour_id": tour_id,
        "name": f"Турнир {tour_id}",
        "city": "Казань",
        "date": "2026-02-16",
        "pos": pos,
        "points": points,
    }


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Не ждать по-настоящему: паузы проверяются отдельным тестом."""
    calls: list[int] = []

    async def pause() -> None:
        calls.append(1)

    monkeypatch.setattr(FillRatingHistoryService, "pause", staticmethod(pause))
    return calls


async def test_requests_rating_list_of_every_given_month(api, http):
    api.always(rating(100))

    await FillRatingHistoryService.collect(http, PLAYER_ID, MONTHS)

    assert [r.form["rating_id"] for r in api.requests] == [
        "202601011",
        "202602011",
        "202603011",
    ]
    assert {r.form["method[0]"] for r in api.requests} == {"rating.details"}
    assert {r.form["player_id"] for r in api.requests} == {str(PLAYER_ID)}


async def test_pauses_between_requests_but_not_before_the_first(api, http, no_waiting):
    api.always(rating(100))

    await FillRatingHistoryService.collect(http, PLAYER_ID, MONTHS)

    assert len(no_waiting) == len(MONTHS) - 1


async def test_single_month_needs_no_pause(api, http, no_waiting):
    api.always(rating(100))

    await FillRatingHistoryService.collect(http, PLAYER_ID, MONTHS[:1])

    assert no_waiting == []


async def test_pause_waits_request_delay(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(fill_rating_history.asyncio, "sleep", fake_sleep)

    await ORIGINAL_PAUSE()

    assert slept == [REQUEST_DELAY]
    assert REQUEST_DELAY == 2


async def test_collects_points_of_every_month(api, http):
    api.reply(rating(100))
    api.reply(rating(200))
    api.reply(rating(300))

    points, _ = await FillRatingHistoryService.collect(http, PLAYER_ID, MONTHS)

    assert points == {MONTHS[0]: 100, MONTHS[1]: 200, MONTHS[2]: 300}


async def test_month_without_rating_counts_as_zero(api, http):
    api.always(rating(None))

    points, _ = await FillRatingHistoryService.collect(http, PLAYER_ID, MONTHS[:1])

    assert points == {MONTHS[0]: 0}


async def test_failed_month_does_not_stop_the_others(api, http):
    api.reply(rating(100))
    api.reply(status=500)
    api.reply(rating(300))

    points, _ = await FillRatingHistoryService.collect(http, PLAYER_ID, MONTHS)

    # запрошены все три месяца, в результат попали удачные
    assert len(api.requests) == 3
    assert points == {MONTHS[0]: 100, MONTHS[2]: 300}


async def test_no_requests_without_missing_months(api, http):
    points, _ = await FillRatingHistoryService.collect(http, PLAYER_ID, [])

    assert points == {}
    assert api.requests == []


def test_months_cover_the_last_twelve_months(freeze_date):
    freeze_date(fill_rating_history, date(2026, 3, 15))

    months = FillRatingHistoryService.get_months()

    assert len(months) == FillRatingHistoryService.MONTHS == 12
    assert months[0] == date(2025, 4, 1)
    assert months[-1] == date(2026, 3, 1)
    assert months == sorted(months)


def test_months_with_any_record_are_skipped():
    # ежемесячная задача пишет сегодняшнюю дату, эта — первое число месяца:
    # заполненным считается месяц, в котором есть хоть одна запись
    dates = [date(2026, 1, 1), date(2026, 3, 17)]

    assert FillRatingHistoryService.filter_missing(MONTHS, dates) == [date(2026, 2, 1)]


def test_all_months_are_missing_for_player_without_points():
    assert FillRatingHistoryService.filter_missing(MONTHS, []) == MONTHS


def test_rate_limit_allows_one_task_per_request_delay():
    assert FillRatingHistoryService.RATE_LIMIT == f"{60 // REQUEST_DELAY}/m" == "30/m"


async def test_collects_tours_of_every_month(api, http):
    api.reply(rating(100, [tour(1, 10)]))
    api.reply(rating(200, [tour(2, 20)]))
    api.reply(rating(300, [tour(3, 30)]))

    _, tours = await FillRatingHistoryService.collect(http, PLAYER_ID, MONTHS)

    assert {t["tour_id"] for t in tours} == {1, 2, 3}


async def test_same_tour_in_several_months_stays_once(api, http):
    # списки соседних месяцев пересекаются
    api.reply(rating(100, [tour(1, 10)]))
    api.reply(rating(200, [tour(1, 10), tour(2, 20)]))
    api.reply(rating(300, [tour(1, 10), tour(2, 20)]))

    _, tours = await FillRatingHistoryService.collect(http, PLAYER_ID, MONTHS)

    assert sorted(t["tour_id"] for t in tours) == [1, 2]


async def test_freshest_month_wins_for_the_same_tour(api, http):
    # очки за турнир со временем пересчитываются; месяцы идут от старых к новым
    api.reply(rating(100, [tour(1, 10, pos="9-16")]))
    api.reply(rating(200, [tour(1, 7, pos="17-32")]))

    _, tours = await FillRatingHistoryService.collect(http, PLAYER_ID, MONTHS[:2])

    assert tours == [
        {
            "tour_id": 1,
            "name": "Турнир 1",
            "city": "Казань",
            "date": date(2026, 2, 16),
            "position": "17-32",
            "points": 7,
        }
    ]


async def test_month_without_tours_adds_nothing(api, http):
    api.always(rating(100))

    _, tours = await FillRatingHistoryService.collect(http, PLAYER_ID, MONTHS)

    assert tours == []


async def test_failed_month_does_not_lose_tours_of_the_others(api, http):
    api.reply(rating(100, [tour(1, 10)]))
    api.reply(status=500)
    api.reply(rating(300, [tour(3, 30)]))

    _, tours = await FillRatingHistoryService.collect(http, PLAYER_ID, MONTHS)

    assert sorted(t["tour_id"] for t in tours) == [1, 3]
