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
