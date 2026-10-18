"""Запрос `tour.card.main` — карточка турнира со списком участников.

Его делает `FillToursService.fetch_tour_players`: при заполнении новых турниров
(`tours.fill_empty`) и при сверке составов (`tours.sync_players`,
`SyncToursService.sync_tour` вызывает ровно эту же функцию).
"""

import json
import time

import aiohttp
import pytest

from src.celery.service.fill_tours import FillToursService
from src.const import HEADERS

TOUR_ID = 307095


async def test_sends_post_with_expected_form(api, http):
    await FillToursService.fetch_tour_players(http, TOUR_ID)

    request = api.request
    assert request.method == "POST"
    assert request.path == "/api/v1/public"
    assert set(request.form) == {"ruid", "method[0]", "tour_id", "part[0]"}
    assert request.form["method[0]"] == "tour.card.main"
    assert request.form["tour_id"] == str(TOUR_ID)
    # без part[0] API отдаёт карточку без состава
    assert request.form["part[0]"] == "players"


async def test_ruid_is_current_milliseconds(api, http):
    await FillToursService.fetch_tour_players(http, TOUR_ID)

    ruid = api.request.form["ruid"]
    assert ruid.isdigit()
    assert abs(int(ruid) - int(time.time() * 1000)) < 60_000


async def test_sends_browser_headers(api, http):
    await FillToursService.fetch_tour_players(http, TOUR_ID)

    # без Origin/Referer апстрим отвечает отказом, поэтому заголовки важны
    for name, value in HEADERS.items():
        assert api.request.headers[name] == value


async def test_parses_json_sent_as_text_html(api, http):
    payload = {"data": {"tour.card.main": {"name": "Кубок Москвы", "players": []}}}
    api.reply(json.dumps(payload), content_type="text/html")

    assert await FillToursService.fetch_tour_players(http, TOUR_ID) == payload


@pytest.mark.parametrize("status", [400, 404, 500, 502])
async def test_raises_on_error_status(api, http, status):
    api.reply(status=status)

    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await FillToursService.fetch_tour_players(http, TOUR_ID)

    assert exc.value.status == status


async def test_makes_exactly_one_request_per_tour(api, http):
    await FillToursService.fetch_tour_players(http, TOUR_ID)
    await FillToursService.fetch_tour_players(http, TOUR_ID + 1)

    assert [r.form["tour_id"] for r in api.requests] == [str(TOUR_ID), str(TOUR_ID + 1)]
