"""Запрос `tour.roster` — постраничный список турниров по фильтрам.

Его делает `SearchToursService.fetch_tours` в задаче `tours.search`: по одному
запросу на страницу выдачи и на каждое сочетание «ранг — локация», потому что
внешнее API фильтрует только по одному рангу и одной локации за запрос.
"""

import json
import time
from datetime import date

import aiohttp
import pytest

from src.celery.service.search_tours import SearchToursService
from src.const import HEADERS
from src.models import SearchSettings

BEGIN = date(2026, 3, 1)
END = date(2026, 6, 1)


def make_settings(**overrides) -> SearchSettings:
    """Настройки поиска в памяти: значения колонок проставляет insert, не конструктор."""
    values = {
        "id": SearchSettings.ROW_ID,
        "period_months": 3,
        "per_page": 10,
        "tour_ranks": [226],
        "tour_gender": 2,
        "location_ids": [1419],
        "age_groups": [131, 132],
    }
    values.update(overrides)
    return SearchSettings(**values)


def page(tour_ids: list[int], page_max: int | None = None) -> str:
    """Ответ одной страницы выдачи."""
    roster: dict = {"records": [{"tour_id": tour_id} for tour_id in tour_ids]}
    if page_max is not None:
        roster["navigator"] = {"page_max": page_max}
    return json.dumps({"data": {"tour.roster": roster}})


async def fetch(http, **overrides):
    """Один запрос страницы с параметрами по умолчанию."""
    params = {
        "settings": make_settings(),
        "begin": BEGIN,
        "end": END,
        "tour_rank": 226,
        "location_id": 1419,
        "page_no": 1,
    }
    params.update(overrides)
    return await SearchToursService.fetch_tours(http, **params)


async def test_sends_post_with_expected_form(api, http):
    await fetch(http, page_no=2)

    request = api.request
    assert request.method == "POST"
    assert request.path == "/api/v1/public"

    form = dict(request.form)
    ruid = form.pop("ruid")
    assert ruid.isdigit()
    assert abs(int(ruid) - int(time.time() * 1000)) < 60_000
    assert form == {
        "method[0]": "tour.roster",
        "page_no": "2",
        "per_page": "10",
        "sort_field": "begin_date",
        "sort_order": "ASC",
        "range": "period",
        "begin": "2026-03-01",
        "end": "2026-06-01",
        "tour_gender": "2",
        "player_age": "131|132",
        "age_group[0]": "131",
        "age_group[1]": "132",
        # `rank` фильтром не является, но фронт шлёт его парой к `tour_rank`
        "tour_rank": "226",
        "rank": "226",
        "location_id": "1419",
    }


async def test_age_groups_expand_into_indexed_fields(api, http):
    await fetch(http, settings=make_settings(age_groups=[131, 132, 133]))

    form = api.request.form
    assert form["player_age"] == "131|132|133"
    assert form["age_group[0]"] == "131"
    assert form["age_group[1]"] == "132"
    assert form["age_group[2]"] == "133"


async def test_rank_and_location_are_omitted_when_not_set(api, http):
    # пустой список фильтров означает «без фильтра», в форму поля не попадают
    await fetch(http, tour_rank=None, location_id=None)

    form = api.request.form
    assert "tour_rank" not in form
    assert "rank" not in form
    assert "location_id" not in form


async def test_sends_browser_headers(api, http):
    await fetch(http)

    for name, value in HEADERS.items():
        assert api.request.headers[name] == value


async def test_parses_json_sent_as_text_html(api, http):
    api.reply(page([1, 2], page_max=1), content_type="text/html")

    assert await fetch(http) == json.loads(page([1, 2], page_max=1))


@pytest.mark.parametrize("status", [400, 404, 500, 502])
async def test_raises_on_error_status(api, http, status):
    api.reply(status=status)

    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await fetch(http)

    assert exc.value.status == status


async def search(http, **overrides) -> list[int]:
    params = {
        "settings": make_settings(),
        "begin": BEGIN,
        "end": END,
        "tour_rank": 226,
        "location_id": 1419,
    }
    params.update(overrides)
    return await SearchToursService.search(http, **params)


async def test_requests_every_page_of_the_result(api, http):
    api.reply(page([1, 2], page_max=3))
    api.reply(page([3], page_max=3))
    api.reply(page([4], page_max=3))

    assert await search(http) == [1, 2, 3, 4]
    assert [r.form["page_no"] for r in api.requests] == ["1", "2", "3"]


async def test_requests_single_page_when_navigator_is_missing(api, http):
    api.reply(page([7]))

    assert await search(http) == [7]
    assert len(api.requests) == 1


async def test_stops_at_max_pages_when_api_lies_about_page_max(api, http):
    # страховка от бесконечной выборки: page_max заведомо больше лимита
    api.always(page([1], page_max=10_000))

    await search(http)

    assert len(api.requests) == SearchToursService.MAX_PAGES


async def test_keeps_filters_on_every_page(api, http):
    api.reply(page([1], page_max=2))
    api.reply(page([2], page_max=2))

    await search(http, tour_rank=300, location_id=42)

    for request in api.requests:
        assert request.form["tour_rank"] == "300"
        assert request.form["rank"] == "300"
        assert request.form["location_id"] == "42"
        assert request.form["begin"] == "2026-03-01"
        assert request.form["end"] == "2026-06-01"
