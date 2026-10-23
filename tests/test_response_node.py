"""Разбор ответов внешнего API, в которых данных нет.

Там, где данных нет, API отдаёт на месте объекта пустой список или null —
парсеры не должны на этом падать.
"""

import pytest

from src.celery.service.fill_matches import FillMatchesService
from src.celery.service.fill_points import FillPointsService
from src.celery.service.fill_tours import FillToursService
from src.celery.service.response import get_node
from src.celery.service.search_tours import SearchToursService

# настоящие ответы: `tour.card.grid` этапа без сетки — [], `rating.details`
# по неизвестному игроку — null
EMPTY = [{}, {"data": {}}, {"data": None}, None]


def answer(method: str, node: object) -> dict:
    return {"data": {method: node}}


@pytest.mark.parametrize("node", [[], None, "", 0, "строка"])
def test_non_object_node_becomes_empty_dict(node):
    assert get_node(answer("tour.card.grid", node), "tour.card.grid") == {}


@pytest.mark.parametrize("payload", EMPTY)
def test_answer_without_data_becomes_empty_dict(payload):
    assert get_node(payload or {}, "tour.card.grid") == {}


def test_object_node_is_returned_as_is():
    assert get_node(answer("tour.card.grid", {"grids": []}), "tour.card.grid") == {"grids": []}


def test_other_methods_are_not_mixed_up():
    assert get_node(answer("tour.card.main", {"name": "турнир"}), "tour.card.grid") == {}


# ---- парсеры на таком ответе ----


@pytest.mark.parametrize("node", [[], None])
def test_grid_of_stage_without_grid(node):
    assert FillMatchesService.get_grid_matches(answer("tour.card.grid", node), 306540) == []


@pytest.mark.parametrize("node", [[], None])
def test_tour_card_parsers_survive(node):
    data = answer("tour.card.main", node)
    assert FillMatchesService.get_matches(data, 306540) == []
    assert FillMatchesService.get_stage_ids(data) == []
    assert FillMatchesService.get_tour_card(data)["is_finished"] is False
    assert FillToursService.get_tour_players(data) == []
    assert FillToursService.get_tour_main(data)["name"] is None


@pytest.mark.parametrize("node", [[], None])
def test_player_card_parser_survives(node):
    assert FillMatchesService.get_player(answer("player.card.main", node), 98883) is None


@pytest.mark.parametrize("node", [[], None])
def test_rating_details_parsers_survive(node):
    data = answer("rating.details", node)
    assert FillPointsService.get_points(data) == 0
    assert FillPointsService.get_tours(data) == []


@pytest.mark.parametrize("node", [[], None])
def test_roster_parsers_survive(node):
    data = answer("tour.roster", node)
    assert SearchToursService.get_page_tour_ids(data) == []
    assert SearchToursService.get_page_max(data) == 1
