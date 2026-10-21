from src.celery.app import celery_app, run_async
from src.celery.service.fill_matches import FillMatchesService
from src.celery.service.fill_points import FillPointsService
from src.celery.service.fill_rating_history import FillRatingHistoryService
from src.celery.service.fill_tours import FillToursService
from src.celery.service.search_tours import SearchToursService
from src.celery.service.sync_tours import SyncToursService


@celery_app.task(name="tours.fill_empty")
def fill_empty_tours_task() -> None:
    """Найти незаполненные турниры и дотянуть по ним данные из внешнего API."""
    run_async(FillToursService.run())


@celery_app.task(name="points.fill")
def fill_points_task() -> None:
    """Добрать очки игроков, у которых нет записи за текущий месяц."""
    run_async(FillPointsService.run())


@celery_app.task(name="points.fill_history", rate_limit=FillRatingHistoryService.RATE_LIMIT)
def fill_rating_history_task(player_id: int) -> None:
    """Добрать историю рейтинга одного игрока за последние месяцы.

    Задача ставится по одной на игрока, rate_limit разводит их запуск
    по времени — внешнее API не любит частых обращений.
    """
    run_async(FillRatingHistoryService.run(player_id))


@celery_app.task(name="tours.sync_players")
def sync_tours_players_task() -> None:
    """Сверить составы предстоящих турниров с внешним API."""
    run_async(SyncToursService.run())


@celery_app.task(name="tours.search")
def search_tours_task() -> None:
    """Найти турниры по сохранённым фильтрам и поставить новые на отслеживание."""
    run_async(SearchToursService.run())


@celery_app.task(name="matches.fill_all")
def fill_matches_all_task() -> None:
    """Поставить задачу разбора матчей на каждый идущий турнир."""
    run_async(FillMatchesService.schedule_all())


@celery_app.task(name="matches.fill", rate_limit=FillMatchesService.RATE_LIMIT)
def fill_matches_task(tour_id: int) -> None:
    """Разобрать матчи одного турнира.

    Задача ставится по одной на турнир, rate_limit разводит их запуск
    по времени — внешнее API не любит частых обращений.
    """
    run_async(FillMatchesService.run(tour_id))
