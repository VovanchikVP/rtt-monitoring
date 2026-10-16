from src.celery.app import celery_app, run_async
from src.celery.service.fill_points import FillPointsService
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


@celery_app.task(name="tours.sync_players")
def sync_tours_players_task() -> None:
    """Сверить составы предстоящих турниров с внешним API."""
    run_async(SyncToursService.run())


@celery_app.task(name="tours.search")
def search_tours_task() -> None:
    """Найти турниры по сохранённым фильтрам и поставить новые на отслеживание."""
    run_async(SearchToursService.run())
