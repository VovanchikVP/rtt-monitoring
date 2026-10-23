"""Задача `matches.fill` — матчи одного турнира.

Задача работает по одному турниру: тянет его матчи и переписывает их в базе,
попутно дозаводя игроков, которых в базе ещё нет. Матчи берутся из расписания
(`tour.card.main`, часть `matches`), а когда его нет — из сеток этапов
(`tour.card.grid`).
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
    "stage_name": "Основной турнир",
    "round_on": 2,
    "rounds": 5,
}


def card(matches: list[dict]) -> dict:
    return {"data": {"tour.card.main": {"tour_id": TOUR_ID, "matches": matches}}}


# ---- запрос ----


async def test_sends_post_with_expected_form(api, http):
    await FillMatchesService.fetch_tour_matches(http, TOUR_ID)

    request = api.request
    assert request.method == "POST"
    assert request.path == "/api/v1/public"
    assert set(request.form) == {"ruid", "method[0]", "tour_id", "part[0]", "part[1]"}
    assert request.form["method[0]"] == "tour.card.main"
    assert request.form["tour_id"] == str(TOUR_ID)
    # этапы приходят тем же ответом: по ним потом запрашиваются сетки
    assert request.form["part[0]"] == "matches"
    assert request.form["part[1]"] == "stages"


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
            "stage_name": "Основной турнир",
            "round_on": 2,
            "rounds": 5,
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


# ---- матчи из сеток этапов ----

STAGE_ID = 96456

# фрагмент настоящей ячейки сетки, лишние поля убраны
CELL = {
    "cell_id": 140211,
    "grid_id": 13753,
    "stage_id": STAGE_ID,
    "match_no": 2,
    "m1": 1520578,
    "m2": 1520579,
    "m1p1": 98883,
    "m1p2": 0,
    "m2p1": 99603,
    "m2p2": 0,
    "m1name": "Исакова М.Д.",
    "m2name": "Батыева Т.В.",
    "winner": 2,
    "score1": 0,
    "score2": 2,
    "score": "2-6,1-6",
    "sdate": "2026-09-21",
    "stime": "10:30:00",
    "match_status_v": "finished",
    "match_finished": 1,
    "stage_name": "Основной турнир",
    "round_on": 2,
}


def grid(cells: list[dict], **fields: object) -> dict:
    one = {"grid_id": 13753, "rounds": 5, "cells": cells, **fields}
    return {"data": {"tour.card.grid": {"grids": [one]}}}


async def test_grid_request_has_expected_form(api, http):
    await FillMatchesService.fetch_stage_grid(http, TOUR_ID, STAGE_ID)

    request = api.request
    assert set(request.form) == {"ruid", "method[0]", "tour_id", "stage_id"}
    assert request.form["method[0]"] == "tour.card.grid"
    assert request.form["tour_id"] == str(TOUR_ID)
    assert request.form["stage_id"] == str(STAGE_ID)


def test_parses_grid_cell():
    assert FillMatchesService.get_grid_matches(grid([CELL]), TOUR_ID) == [
        {
            "tour_id": TOUR_ID,
            "first_player_id": 98883,
            "second_player_id": 99603,
            "winner_player_id": 99603,
            "first_score": 0,
            "second_score": 2,
            "score": "2-6,1-6",
            "status": "finished",
            "date": date(2026, 9, 21),
            "stage_name": "Основной турнир",
            "round_on": 2,
            # число кругов задано у сетки целиком, в ячейке его нет
            "rounds": 5,
        }
    ]


@pytest.mark.parametrize("field", ["m1p1", "m2p1"])
def test_skips_cell_without_opponent(field):
    # в сетке есть ячейки, куда игрок ещё не вышел: там стоит 0
    assert FillMatchesService.get_grid_matches(grid([{**CELL, field: 0}]), TOUR_ID) == []


@pytest.mark.parametrize("field", ["m1p2", "m2p2"])
def test_skips_doubles_cell(field):
    # под матч в таблице заведены два игрока, пару туда не положить
    assert FillMatchesService.get_grid_matches(grid([{**CELL, field: 99604}]), TOUR_ID) == []


def test_unplayed_cell_has_no_score():
    # у несыгранной ячейки счёт приходит нулями — это не 0:0
    cell = {**CELL, "winner": 0, "score1": 0, "score2": 0, "score": "0", "sdate": "0"}
    assert FillMatchesService.get_grid_matches(grid([cell]), TOUR_ID) == [
        {
            "tour_id": TOUR_ID,
            "first_player_id": 98883,
            "second_player_id": 99603,
            "winner_player_id": None,
            "first_score": None,
            "second_score": None,
            "score": None,
            "status": "finished",
            "date": None,
            "stage_name": "Основной турнир",
            "round_on": 2,
            "rounds": 5,
        }
    ]


def test_cell_with_score_but_without_winner_keeps_sets():
    cell = {**CELL, "winner": 0}
    match = FillMatchesService.get_grid_matches(grid([cell]), TOUR_ID)[0]
    assert match["winner_player_id"] is None
    assert (match["first_score"], match["second_score"]) == (0, 2)


def test_collects_cells_of_every_grid():
    data = {
        "data": {
            "tour.card.grid": {
                "grids": [
                    {"grid_id": 1, "cells": [CELL]},
                    {"grid_id": 2, "cells": [{**CELL, "m1p1": 111}]},
                ]
            }
        }
    }
    matches = FillMatchesService.get_grid_matches(data, TOUR_ID)
    assert [m["first_player_id"] for m in matches] == [98883, 111]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": {}},
        {"data": {"tour.card.grid": {}}},
        {"data": {"tour.card.grid": {"grids": None}}},
    ],
)
def test_answer_without_grids_gives_empty_list(payload):
    assert FillMatchesService.get_grid_matches(payload, TOUR_ID) == []


def test_grid_without_cells_gives_empty_list():
    assert FillMatchesService.get_grid_matches(grid(None), TOUR_ID) == []


# ---- этап и круги ----


def test_cell_rounds_win_over_the_grid():
    # у ячейки своё число кругов встречается не всегда, но если есть — оно главнее
    match = FillMatchesService.get_grid_matches(grid([{**CELL, "rounds": 3}]), TOUR_ID)[0]
    assert match["rounds"] == 3


def test_grid_without_rounds_leaves_the_field_empty():
    data = {"data": {"tour.card.grid": {"grids": [{"grid_id": 1, "cells": [CELL]}]}}}
    assert FillMatchesService.get_grid_matches(data, TOUR_ID)[0]["rounds"] is None


@pytest.mark.parametrize("field", ["stage_name", "round_on"])
def test_missing_stage_and_round_become_none(field):
    cell = {k: v for k, v in CELL.items() if k != field}
    assert FillMatchesService.get_grid_matches(grid([cell]), TOUR_ID)[0][field] is None


def test_empty_stage_name_becomes_none():
    match = FillMatchesService.get_matches(card([{**MATCH, "stage_name": ""}]), TOUR_ID)[0]
    assert match["stage_name"] is None


@pytest.mark.parametrize(("value", "expected"), [("3", 3), (3, 3), (None, None), ("", None)])
def test_round_is_read_as_a_number(value, expected):
    match = FillMatchesService.get_matches(card([{**MATCH, "round_on": value}]), TOUR_ID)[0]
    assert match["round_on"] == expected


def test_non_numeric_round_is_skipped_with_a_warning(caplog):
    # поле необязательное: лучше пропустить его, чем уронить разбор турнира
    match = FillMatchesService.get_matches(card([{**MATCH, "rounds": "четыре"}]), TOUR_ID)[0]

    assert match["rounds"] is None
    assert "четыре" in caplog.text


# ---- этапы турнира ----


def test_parses_stage_ids():
    data = {
        "data": {
            "tour.card.main": {
                "stages": [
                    {"stage_id": 96456, "name": "Основной турнир"},
                    {"stage_id": 96457, "name": "Отборочный турнир"},
                ]
            }
        }
    }
    assert FillMatchesService.get_stage_ids(data) == [96456, 96457]


def test_stage_without_id_is_skipped():
    data = {"data": {"tour.card.main": {"stages": [{"stage_id": 0}, {"name": "без id"}]}}}
    assert FillMatchesService.get_stage_ids(data) == []


@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"data": {"tour.card.main": {}}}])
def test_answer_without_stages_gives_empty_list(payload):
    assert FillMatchesService.get_stage_ids(payload) == []


async def test_collect_grids_walks_every_stage(api, http):
    api.always(json.dumps(grid([CELL])))

    matches = await FillMatchesService.collect_grids(http, TOUR_ID, [96456, 96457])

    assert len(matches) == 2
    assert [r.form["stage_id"] for r in api.requests] == ["96456", "96457"]


async def test_broken_stage_does_not_drop_the_rest(api, http):
    # один сбойный этап не должен ронять остальные
    api.reply(status=500)
    api.always(json.dumps(grid([CELL])))

    matches = await FillMatchesService.collect_grids(http, TOUR_ID, [96456, 96457])

    assert len(matches) == 1


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
