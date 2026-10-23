"""Остановка разбора очереди, пока внешнее API требует проверку.

Отложить одну задачу мало: соседние ходят в то же API и, сорвавшись следом,
только продлевают блокировку. Поэтому воркер отписывается от очереди.
"""

from dataclasses import dataclass, field

import pytest

from src.celery import throttle
from src.const import THROTTLE_DELAY, THROTTLE_MAX_DELAY

WORKER = "celery@rtt-worker-1"


@dataclass
class Call:
    """Команда, отправленная воркеру."""

    queue: str
    destination: list[str] | None


@dataclass
class FakeControl:
    """Управление celery, которое запоминает команды вместо отправки."""

    cancelled: list[Call] = field(default_factory=list)
    added: list[Call] = field(default_factory=list)

    def cancel_consumer(self, queue: str, destination: list[str] | None = None) -> None:
        self.cancelled.append(Call(queue, destination))

    def add_consumer(self, queue: str, destination: list[str] | None = None) -> None:
        self.added.append(Call(queue, destination))


@dataclass
class FakeTimer:
    """Таймер, который запускается только вручную."""

    seconds: float
    function: object
    args: tuple
    daemon: bool = False
    started: bool = False
    cancelled: bool = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        self.function(*self.args)


@pytest.fixture
def worker(monkeypatch):
    """Подменить управление celery и таймер, вернуть то и другое тесту."""
    control = FakeControl()
    timers: list[FakeTimer] = []

    def timer(seconds, function, args=()):
        timers.append(FakeTimer(seconds, function, tuple(args)))
        return timers[-1]

    monkeypatch.setattr(throttle.celery_app, "control", control)
    monkeypatch.setattr(throttle.threading, "Timer", timer)
    monkeypatch.setattr(throttle, "_timer", None)
    yield control, timers
    monkeypatch.setattr(throttle, "_timer", None)


def test_pause_unsubscribes_the_worker_from_its_queue(worker):
    control, _ = worker

    throttle.pause_consuming(WORKER, 600)

    assert control.cancelled == [Call(throttle.queue_name(), [WORKER])]
    assert control.added == []


def test_pause_schedules_the_return(worker):
    _, timers = worker

    throttle.pause_consuming(WORKER, 600)

    assert len(timers) == 1
    assert timers[0].seconds == 600
    assert timers[0].started is True
    # демон: таймер не должен держать воркер при остановке
    assert timers[0].daemon is True


def test_timer_brings_the_worker_back(worker):
    control, timers = worker
    throttle.pause_consuming(WORKER, 600)

    timers[0].fire()

    assert control.added == [Call(throttle.queue_name(), [WORKER])]
    assert throttle.is_paused() is False


def test_repeated_block_restarts_the_countdown(worker):
    control, timers = worker
    throttle.pause_consuming(WORKER, 600)

    throttle.pause_consuming(WORKER, 900)

    # прежний таймер снят, иначе он вернул бы воркера раньше срока
    assert timers[0].cancelled is True
    assert timers[1].seconds == 900
    assert len(control.cancelled) == 2


def test_pause_is_visible_until_the_timer_fires(worker):
    _, timers = worker
    assert throttle.is_paused() is False

    throttle.pause_consuming(WORKER, 600)
    assert throttle.is_paused() is True

    timers[0].fire()
    assert throttle.is_paused() is False


def test_command_without_worker_name_goes_to_everyone():
    # имени воркера может не быть — тогда команда широковещательная
    assert throttle.destination(None) is None
    assert throttle.destination(WORKER) == [WORKER]


def test_queue_is_taken_from_the_celery_config():
    assert throttle.queue_name() == throttle.celery_app.conf.task_default_queue


# ---- пауза растёт, пока блокировка держится ----


@pytest.fixture
def fresh(monkeypatch):
    """Сбросить счёт блокировок подряд."""
    monkeypatch.setattr(throttle, "_failures", 0)


def test_pause_from_the_api_is_respected_as_is(fresh):
    # своя пауза API точнее любой угаданной
    assert throttle.next_delay(42) == 42


def test_pause_doubles_while_the_block_holds(fresh):
    delays = [throttle.next_delay(0) for _ in range(4)]

    assert delays == [
        THROTTLE_DELAY,
        THROTTLE_DELAY * 2,
        THROTTLE_DELAY * 4,
        THROTTLE_DELAY * 8,
    ]


def test_pause_does_not_grow_past_the_cap(fresh):
    for _ in range(20):
        delay = throttle.next_delay(0)

    assert delay == THROTTLE_MAX_DELAY


def test_successful_request_resets_the_count(fresh):
    throttle.next_delay(0)
    throttle.next_delay(0)

    throttle.clear()

    assert throttle.next_delay(0) == THROTTLE_DELAY
