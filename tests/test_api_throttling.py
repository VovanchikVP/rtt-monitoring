"""Ответ внешнего API «требуется проверка» — 428 с кодом `/captcha/required`.

Капчу фоновой задаче не пройти, поэтому запрос не считается ошибкой: работа
откладывается и повторяется позже, а по списку дальше задача не идёт —
следующий запрос упёрся бы в ту же стену.
"""

import json
from datetime import date

import aiohttp
import pytest

from src.celery import tasks
from src.celery.service.api import ThrottledError, get_retry_after, post
from src.celery.service.fill_matches import FillMatchesService
from src.celery.service.fill_points import FillPointsService
from src.celery.service.fill_rating_history import FillRatingHistoryService
from src.celery.tasks import THROTTLE_RETRIES, run_task
from src.const import THROTTLE_DELAY

FORM = [("method[0]", "rating.details"), ("player_id", "48215")]


@pytest.fixture
def no_pause(monkeypatch):
    """Убрать паузы между запросами: в тесте ждать нечего."""

    async def instantly() -> None:
        return None

    monkeypatch.setattr(FillRatingHistoryService, "pause", classmethod(lambda cls: instantly()))
    monkeypatch.setattr(FillMatchesService, "pause", classmethod(lambda cls: instantly()))


# настоящий ответ API, лишние поля убраны
CAPTCHA = json.dumps(
    {
        "status": "error",
        "code": "/captcha/required",
        "desc": "Требуется проверка",
        "data": {"method": "rating.details", "retry_after": 0},
    }
)


# ---- клиент ----


async def test_428_becomes_throttled_error(api, http):
    api.always(CAPTCHA, status=428)

    with pytest.raises(ThrottledError):
        await post(http, FORM)


async def test_captcha_without_its_own_pause_falls_back_to_ours(api, http):
    # retry_after в ответе нулевой: вернувшись сразу, упрёмся в ту же проверку
    api.always(CAPTCHA, status=428)

    with pytest.raises(ThrottledError) as exc:
        await post(http, FORM)
    assert exc.value.retry_after == THROTTLE_DELAY


async def test_pause_from_the_answer_is_respected(api, http):
    body = json.dumps({"code": "/captcha/required", "data": {"retry_after": 42}})
    api.always(body, status=428)

    with pytest.raises(ThrottledError) as exc:
        await post(http, FORM)
    assert exc.value.retry_after == 42


@pytest.mark.parametrize("status", [400, 404, 500, 502])
async def test_other_errors_stay_errors(api, http, status):
    api.always(status=status)

    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await post(http, FORM)
    assert exc.value.status == status


async def test_good_answer_is_parsed(api, http):
    payload = {"data": {"rating.details": {"rating": {"points": 480}}}}
    api.always(json.dumps(payload))

    assert await post(http, FORM) == payload


# ---- выбор паузы ----


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"data": {"retry_after": 30}}, 30),
        ({"data": {"retry_after": "30"}}, 30),
        ({"data": {"retry_after": 0}}, THROTTLE_DELAY),
        ({"data": {}}, THROTTLE_DELAY),
        ({"data": []}, THROTTLE_DELAY),
        ({}, THROTTLE_DELAY),
        ([], THROTTLE_DELAY),
    ],
)
def test_pause_is_read_from_the_body(body, expected):
    assert get_retry_after(body, {}) == expected


def test_header_is_used_when_the_body_is_silent():
    assert get_retry_after({"data": {"retry_after": 0}}, {"Retry-After": "90"}) == 90


def test_body_wins_over_the_header():
    assert get_retry_after({"data": {"retry_after": 15}}, {"Retry-After": "90"}) == 15


# ---- задача не идёт дальше по списку ----


async def test_grid_walk_stops_on_throttling(api, http):
    api.always(CAPTCHA, status=428)

    with pytest.raises(ThrottledError):
        await FillMatchesService.collect_grids(http, 306540, [96456, 96457])

    # второй этап даже не запрашивался
    assert len(api.requests) == 1


async def test_player_cards_stop_on_throttling(api, http):
    api.always(CAPTCHA, status=428)

    with pytest.raises(ThrottledError):
        await FillMatchesService.add_players(http, {98883, 99603})

    assert len(api.requests) == 1


async def test_rating_history_stops_on_throttling(api, http, no_pause):
    api.always(CAPTCHA, status=428)

    with pytest.raises(ThrottledError):
        await FillRatingHistoryService.collect(http, 48215, [date(2026, 1, 1), date(2026, 2, 1)])

    assert len(api.requests) == 1


# ---- обычная ошибка по-прежнему не роняет обход ----


async def test_single_broken_stage_is_still_skipped(api, http):
    api.reply(status=500)
    api.always(json.dumps({"data": {"tour.card.grid": {"grids": []}}}))

    assert await FillMatchesService.collect_grids(http, 306540, [96456, 96457]) == []
    assert len(api.requests) == 2


async def test_fill_points_stops_on_throttling(api, monkeypatch):
    # поштучный except в run не должен глотать просьбу подождать
    async def players() -> list[int]:
        return [101, 102, 103]

    monkeypatch.setattr(FillPointsService, "get_players_without_points", players)
    api.always(CAPTCHA, status=428)

    with pytest.raises(ThrottledError):
        await FillPointsService.run()

    # на втором игроке задача уже не настаивает
    assert len(api.requests) == 1


# ---- задача откладывает повтор ----


class FakeRequest:
    hostname = "celery@rtt-worker-1"


class FakeTask:
    """Задача celery, которая запоминает вызов retry вместо постановки в очередь."""

    name = "points.fill"
    request = FakeRequest()

    def __init__(self) -> None:
        self.countdown = None

    def retry(self, countdown: int, max_retries: int) -> Exception:
        self.countdown = countdown
        self.max_retries = max_retries
        return Retry()


class Retry(Exception):
    """То, что celery бросает из `task.retry`."""


async def throttled() -> None:
    raise ThrottledError(42)


async def boom() -> None:
    raise RuntimeError("настоящая ошибка")


@pytest.fixture
def paused(monkeypatch):
    """Перехватить остановку очереди: до брокера в тесте не ходим."""
    calls = []
    monkeypatch.setattr(
        tasks, "pause_consuming", lambda worker, seconds: calls.append((worker, seconds))
    )
    return calls


def test_throttled_task_is_retried_with_the_asked_pause(caplog, paused):
    task = FakeTask()

    with pytest.raises(Retry):
        run_task(task, throttled())

    assert task.countdown == 42
    assert task.max_retries == THROTTLE_RETRIES
    # в логе предупреждение, а не трассировка
    assert "отложена на 42" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_throttled_task_also_stops_the_queue(paused):
    # соседние задачи ходят в то же API и продлевали бы блокировку
    with pytest.raises(Retry):
        run_task(FakeTask(), throttled())

    assert paused == [("celery@rtt-worker-1", 42)]


def test_other_errors_are_not_retried(paused):
    task = FakeTask()

    with pytest.raises(RuntimeError):
        run_task(task, boom())

    assert task.countdown is None
    # обычная ошибка очередь не трогает
    assert paused == []
