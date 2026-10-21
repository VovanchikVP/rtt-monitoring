"""Запрос `tour.card.main` с частью `matches` — задача `matches.fill`.

Задача работает по одному турниру: тянет его матчи и переписывает их в базе,
попутно дозаводя игроков, которых в базе ещё нет.
"""

import json
import time
from datetime import date

import aiohttp
import pytest

from src.celery.service.fill_matches import FillMatchesService
from src.const import HEADERS

TOUR_ID = 305042

# фрагмент настоящего ответа API, лишние поля убраны
MATCH = {
    "match_id": 404476,
    "tour_id": TOUR_ID,
    "m1p1": 98883,
    "m1p2": 0,
    "m2p1": 99603,
    "m2p2": 0,
    "match_date": "2026-06-01",
    "winner": 1,
    "score1": 2,
    "score2": 0,
    "score": "6-0,6-1",
    "status": 1280,
    "status_v": "finished",
    "status_n": "Завершен",
}


def card(matches: list[dict]) -> dict:
    return {"data": {"tour.card.main": {"tour_id": TOUR_ID, "matches": matches}}}


# ---- запрос ----


async def test_sends_post_with_expected_form(api, http):
    await FillMatchesService.fetch_tour_matches(http, TOUR_ID)

    request = api.request
    assert request.method == "POST"
    assert request.path == "/api/v1/public"
    assert set(request.form) == {"ruid", "method[0]", "tour_id", "part[0]"}
    assert request.form["method[0]"] == "tour.card.main"
    assert request.form["tour_id"] == str(TOUR_ID)
    assert request.form["part[0]"] == "matches"


async def test_ruid_is_current_milliseconds(api, http):
    await FillMatchesService.fetch_tour_matches(http, TOUR_ID)

    ruid = api.request.form["ruid"]
    assert ruid.isdigit()
    assert abs(int(ruid) - int(time.time() * 1000)) < 60_000


async def test_sends_browser_headers(api, http):
    await FillMatchesService.fetch_tour_matches(http, TOUR_ID)

    for name, value in HEADERS.items():
        assert api.request.headers[name] == value


async def test_parses_json_sent_as_text_html(api, http):
    payload = card([MATCH])
    api.reply(json.dumps(payload), content_type="text/html")

    assert await FillMatchesService.fetch_tour_matches(http, TOUR_ID) == payload


@pytest.mark.parametrize("status", [400, 404, 500, 502])
async def test_raises_on_error_status(api, http, status):
    api.reply(status=status)

    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await FillMatchesService.fetch_tour_matches(http, TOUR_ID)

    assert exc.value.status == status


# ---- разбор матчей ----


def test_parses_match():
    assert FillMatchesService.get_matches(card([MATCH]), TOUR_ID) == [
        {
            "tour_id": TOUR_ID,
            "first_player_id": 98883,
            "second_player_id": 99603,
            "winner_player_id": 98883,
            "first_score": 2,
            "second_score": 0,
            "score": "6-0,6-1",
            "status": "Завершен",
            "date": date(2026, 6, 1),
        }
    ]


def test_winner_two_points_to_second_player():
    match = FillMatchesService.get_matches(card([{**MATCH, "winner": 2}]), TOUR_ID)[0]
    assert match["winner_player_id"] == 99603


@pytest.mark.parametrize("winner", [0, None])
def test_match_without_winner_has_none(winner):
    match = FillMatchesService.get_matches(card([{**MATCH, "winner": winner}]), TOUR_ID)[0]
    assert match["winner_player_id"] is None


@pytest.mark.parametrize("field", ["m1p1", "m2p1"])
def test_skips_match_without_opponent(field):
    # в сетке есть пары, куда соперник ещё не вышел: там стоит 0
    assert FillMatchesService.get_matches(card([{**MATCH, field: 0}]), TOUR_ID) == []


def test_bad_date_becomes_none():
    match = FillMatchesService.get_matches(card([{**MATCH, "match_date": "1900-01-01"}]), TOUR_ID)[
        0
    ]
    assert match["date"] is None


def test_empty_score_becomes_none():
    match = FillMatchesService.get_matches(card([{**MATCH, "score": "", "status_n": ""}]), TOUR_ID)[
        0
    ]
    assert match["score"] is None
    assert match["status"] is None


def test_tour_id_comes_from_the_argument():
    # в ответе tour_id тоже есть, но доверяем тому, по которому запрашивали
    match = FillMatchesService.get_matches(card([MATCH]), 999)[0]
    assert match["tour_id"] == 999


@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"data": {"tour.card.main": {}}}])
def test_answer_without_matches_gives_empty_list(payload):
    assert FillMatchesService.get_matches(payload, TOUR_ID) == []


def test_null_matches_gives_empty_list():
    assert (
        FillMatchesService.get_matches({"data": {"tour.card.main": {"matches": None}}}, TOUR_ID)
        == []
    )


def test_collects_player_ids_of_all_matches():
    matches = FillMatchesService.get_matches(
        card([MATCH, {**MATCH, "m1p1": 111, "m2p1": 98883}]), TOUR_ID
    )
    assert FillMatchesService.get_player_ids(matches) == {98883, 99603, 111}


# ---- карточка игрока ----

PLAYER_CARD = {
    "data": {
        "player.card.main": {
            "player_id": 98883,
            "name_f": "Портная",
            "name_i": "Ксения",
            "name_o": "Владиславовна",
            "birth_date": "2014-07-16",
            "doc_city": "Рязань, Рязанская область, Центральный ФО, Россия",
        }
    }
}


async def test_player_request_has_expected_form(api, http):
    await FillMatchesService.fetch_player(http, 98883)

    request = api.request
    assert set(request.form) == {"ruid", "method[0]", "player_id"}
    assert request.form["method[0]"] == "player.card.main"
    assert request.form["player_id"] == "98883"


def test_parses_player_card():
    assert FillMatchesService.get_player(PLAYER_CARD, 98883) == {
        "id": 98883,
        "name": "Портная Ксения Владиславовна",
        # город в карточке записан путём, в базе храним только сам город
        "city": "Рязань",
        "birth_date": date(2014, 7, 16),
    }


def test_player_without_patronymic():
    card_ = {
        "data": {"player.card.main": {**PLAYER_CARD["data"]["player.card.main"], "name_o": ""}}
    }
    assert FillMatchesService.get_player(card_, 98883)["name"] == "Портная Ксения"


def test_player_without_birth_date_is_skipped():
    # birth_date в таблице обязателен — такого игрока не заводим
    card_ = {
        "data": {"player.card.main": {**PLAYER_CARD["data"]["player.card.main"], "birth_date": ""}}
    }
    assert FillMatchesService.get_player(card_, 98883) is None


def test_player_without_any_name_part_is_skipped():
    card_ = {
        "data": {
            "player.card.main": {
                **PLAYER_CARD["data"]["player.card.main"],
                "name_f": "",
                "name_i": "",
                "name_o": "",
            }
        }
    }
    assert FillMatchesService.get_player(card_, 98883) is None


def test_empty_player_card_is_skipped():
    assert FillMatchesService.get_player({"data": {}}, 98883) is None


# ---- отбор матчей по наличию игроков ----


def test_match_is_playable_only_with_both_players_known():
    match = FillMatchesService.get_matches(card([MATCH]), TOUR_ID)[0]
    assert FillMatchesService.is_playable(match, {98883, 99603}) is True
    assert FillMatchesService.is_playable(match, {98883}) is False
    assert FillMatchesService.is_playable(match, set()) is False


# ---- карточка турнира из того же ответа ----

# фрагмент настоящего ответа API, лишние поля убраны
TOUR_CARD = {
    "tour_id": TOUR_ID,
    "name": "Первенство Хабаровского края",
    "is_finished": 1,
    "begin_date": "2026-06-01",
    "end_date": "2026-06-07",
    "location": "Хабаровск",
    "location_full": "Хабаровск, Хабаровский край, Дальневосточный ФО, Россия",
}


def test_parses_tour_card():
    assert FillMatchesService.get_tour_card({"data": {"tour.card.main": TOUR_CARD}}) == {
        "begin_date": date(2026, 6, 1),
        "end_date": date(2026, 6, 7),
        "location": "Хабаровск",
        "location_full": "Хабаровск, Хабаровский край, Дальневосточный ФО, Россия",
        "is_finished": True,
    }


@pytest.mark.parametrize(("value", "expected"), [(1, True), (0, False)])
def test_is_finished_comes_as_number(value, expected):
    card_ = {"data": {"tour.card.main": {**TOUR_CARD, "is_finished": value}}}
    assert FillMatchesService.get_tour_card(card_)["is_finished"] is expected


def test_missing_is_finished_counts_as_not_finished():
    card_ = {"data": {"tour.card.main": {}}}
    assert FillMatchesService.get_tour_card(card_)["is_finished"] is False


def test_empty_tour_fields_become_none():
    card_ = {
        "data": {
            "tour.card.main": {
                **TOUR_CARD,
                "location": "",
                "location_full": "",
                "begin_date": "1900-01-01",
                "end_date": "",
            }
        }
    }
    assert FillMatchesService.get_tour_card(card_) == {
        "begin_date": None,
        "end_date": None,
        "location": None,
        "location_full": None,
        "is_finished": True,
    }


@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"data": {"tour.card.main": None}}])
def test_tour_card_of_empty_answer_has_all_fields(payload):
    # полям UPDATE нужны значения, даже если в ответе ничего нет
    assert FillMatchesService.get_tour_card(payload) == {
        "begin_date": None,
        "end_date": None,
        "location": None,
        "location_full": None,
        "is_finished": False,
    }
