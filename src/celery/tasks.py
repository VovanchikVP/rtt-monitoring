import logging
from collections.abc import Coroutine

from celery import Task
from src.celery.app import celery_app, run_async
from src.celery.service.api import ThrottledError
from src.celery.service.fill_matches import FillMatchesService
from src.celery.service.fill_player_tours import FillPlayerToursService
from src.celery.service.fill_points import FillPointsService
from src.celery.service.fill_rating_history import FillRatingHistoryService
from src.celery.service.fill_tours import FillToursService
from src.celery.service.search_tours import SearchToursService
from src.celery.service.sync_tours import SyncToursService

logger = logging.getLogger(__name__)

# сколько раз откладывать задачу, пока внешнее API требует проверку
THROTTLE_RETRIES = 6


def run_task(task: Task, coro: Coroutine) -> None:
    """Выполнить корутину задачи, отложив её, если API просит подождать.

    Капчу фоновой задаче не пройти, остаётся вернуться позже — блокировка
    снимается сама. Повторов с запасом, но не бесконечно: иначе отложенные
    задачи копились бы в очереди без всякой надежды.
    """
    try:
        run_async(coro)
    except ThrottledError as error:
        logger.warning(
            "Задача %s отложена на %s с: внешнее API требует проверку",
            task.name,
            error.retry_after,
        )
        # from None: трассировка просьбы подождать в логе ни к чему
        raise task.retry(countdown=error.retry_after, max_retries=THROTTLE_RETRIES) from None


@celery_app.task(bind=True, name="tours.fill_empty")
def fill_empty_tours_task(self: Task) -> None:
    """Найти незаполненные турниры и дотянуть по ним данные из внешнего API."""
    run_task(self, FillToursService.run())


@celery_app.task(bind=True, name="points.fill")
def fill_points_task(self: Task) -> None:
    """Добрать очки игроков, у которых нет записи за текущий месяц."""
    run_task(self, FillPointsService.run())


@celery_app.task(
    bind=True, name="points.fill_history", rate_limit=FillRatingHistoryService.RATE_LIMIT
)
def fill_rating_history_task(self: Task, player_id: int) -> None:
    """Добрать историю рейтинга одного игрока за последние месяцы.

    Задача ставится по одной на игрока, rate_limit разводит их запуск
    по времени — внешнее API не любит частых обращений.
    """
    run_task(self, FillRatingHistoryService.run(player_id))


@celery_app.task(bind=True, name="tours.fill_player", rate_limit=FillPlayerToursService.RATE_LIMIT)
def fill_player_tours_task(self: Task, player_id: int) -> None:
    """Обновить результаты одного игрока по сыгранным турнирам.

    Задача ставится по одной на игрока, rate_limit разводит их запуск
    по времени — внешнее API не любит частых обращений.
    """
    run_task(self, FillPlayerToursService.run(player_id))


@celery_app.task(bind=True, name="tours.sync_players")
def sync_tours_players_task(self: Task) -> None:
    """Сверить составы предстоящих турниров с внешним API."""
    run_task(self, SyncToursService.run())


@celery_app.task(bind=True, name="tours.search")
def search_tours_task(self: Task) -> None:
    """Найти турниры по сохранённым фильтрам и поставить новые на отслеживание."""
    run_task(self, SearchToursService.run())


@celery_app.task(bind=True, name="matches.fill_all")
def fill_matches_all_task(self: Task) -> None:
    """Поставить задачу разбора матчей на каждый идущий турнир."""
    run_task(self, FillMatchesService.schedule_all())


@celery_app.task(bind=True, name="matches.fill", rate_limit=FillMatchesService.RATE_LIMIT)
def fill_matches_task(self: Task, tour_id: int) -> None:
    """Разобрать матчи одного турнира.

    Задача ставится по одной на турнир, rate_limit разводит их запуск
    по времени — внешнее API не любит частых обращений.
    """
    run_task(self, FillMatchesService.run(tour_id))
