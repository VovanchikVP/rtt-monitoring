from src.celery.app import celery_app, run_async
from src.celery.service.fill_tours import fill_empty_tours


@celery_app.task(name="tours.fill_empty")
def fill_empty_tours_task() -> None:
    """Найти незаполненные турниры и дотянуть по ним данные из внешнего API."""
    run_async(fill_empty_tours())
