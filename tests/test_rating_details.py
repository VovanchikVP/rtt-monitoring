"""Запрос `rating.details` — карточка игрока в текущем рейтинг-листе.

Его делает `FillPointsService.fetch_rating_details` в задаче `points.fill`,
по одному запросу на игрока без записи об очках за текущий месяц.
"""

import json
import time
from datetime import date

import aiohttp
import pytest

from src.celery.service import fill_points
from src.celery.service.fill_points import FillPointsService
from src.const import HEADERS

PLAYER_ID = 48215


async def test_sends_post_with_expected_form(api, http):
    await FillPointsService.fetch_rating_details(http, PLAYER_ID)

    request = api.request
    assert request.method == "POST"
    assert request.path == "/api/v1/public"
    assert set(request.form) == {"ruid", "method[0]", "rating_id", "player_id"}
    assert request.form["method[0]"] == "rating.details"
    assert request.form["player_id"] == str(PLAYER_ID)


async def test_rating_id_points_to_current_month(api, http, freeze_date):
    freeze_date(fill_points, date(2026, 3, 15))

    await FillPointsService.fetch_rating_details(http, PLAYER_ID)

    # идентификатор рейтинг-листа — первое число текущего месяца плюс «1»
    assert api.request.form["rating_id"] == "202603011"


async def test_ruid_is_current_milliseconds(api, http):
    await FillPointsService.fetch_rating_details(http, PLAYER_ID)

    ruid = api.request.form["ruid"]
    assert ruid.isdigit()
    assert abs(int(ruid) - int(time.time() * 1000)) < 60_000


async def test_sends_browser_headers(api, http):
    await FillPointsService.fetch_rating_details(http, PLAYER_ID)

    for name, value in HEADERS.items():
        assert api.request.headers[name] == value


async def test_parses_json_sent_as_text_html(api, http):
    payload = {"data": {"rating.details": {"rating": {"points": 1234}}}}
    api.reply(json.dumps(payload), content_type="text/html")

    assert await FillPointsService.fetch_rating_details(http, PLAYER_ID) == payload


@pytest.mark.parametrize("status", [400, 404, 500, 502])
async def test_raises_on_error_status(api, http, status):
    api.reply(status=status)

    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await FillPointsService.fetch_rating_details(http, PLAYER_ID)

    assert exc.value.status == status


# ---- разбор списка турниров из того же ответа ----

# фрагмент настоящего ответа API
TOUR = {
    "id": 20020101,
    "rating_id": 202610011,
    "player_id": PLAYER_ID,
    "tour_id": 305042,
    "name": "Первенство Хабаровского края",
    "city": "Хабаровск",
    "date": "2026-06-01",
    "rank": 226,
    "category": "III А",
    "result": 4,
    "pos": "25-32",
    "points": 9,
}


def details(tours: list[dict]) -> dict:
    return {"data": {"rating.details": {"rating": {"points": 1}, "tours": tours}}}


def test_parses_tour_result():
    assert FillPointsService.get_tours(details([TOUR])) == [
        {
            "tour_id": 305042,
            "name": "Первенство Хабаровского края",
            "city": "Хабаровск",
            "date": date(2026, 6, 1),
            "position": "25-32",
            "points": 9,
        }
    ]


def test_keeps_place_range_as_string():
    # место бывает и одиночным, и диапазоном — в базе это строка
    single = FillPointsService.get_tours(details([{**TOUR, "pos": "10"}]))
    assert single[0]["position"] == "10"


def test_numeric_place_becomes_string():
    assert FillPointsService.get_tours(details([{**TOUR, "pos": 10}]))[0]["position"] == "10"


@pytest.mark.parametrize("empty", [None, ""])
def test_missing_place_is_none(empty):
    assert FillPointsService.get_tours(details([{**TOUR, "pos": empty}]))[0]["position"] is None


def test_tour_date_fills_both_bounds():
    # в этом блоке у турнира одна дата — она же начало и конец
    tour = FillPointsService.get_tours(details([TOUR]))[0]
    assert tour["date"] == date(2026, 6, 1)


def test_bad_date_becomes_none():
    assert FillPointsService.get_tours(details([{**TOUR, "date": "1900-01-01"}]))[0]["date"] is None


def test_skips_entries_without_tour_id():
    assert FillPointsService.get_tours(details([{**TOUR, "tour_id": None}])) == []


def test_deduplicates_by_tour_id():
    # побеждает последняя запись: дальше по месяцам идёт более свежий ответ
    tours = FillPointsService.get_tours(details([TOUR, {**TOUR, "points": 42}]))
    assert len(tours) == 1
    assert tours[0]["points"] == 42


@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"data": {"rating.details": {}}}])
def test_answer_without_tours_gives_empty_list(payload):
    assert FillPointsService.get_tours(payload) == []


def test_null_tours_gives_empty_list():
    assert FillPointsService.get_tours({"data": {"rating.details": {"tours": None}}}) == []
