import asyncio
from collections.abc import Coroutine

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init
from src.config.config import settings
from src.models.base import engine

celery_app = Celery(
    "rtt_monitoring",
    broker=settings.CELERY_BROKER_URL,
    include=["src.celery.tasks"],
)

celery_app.conf.update(
    # результаты задач не используются, хранилище под них не поднимаем
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_max_tasks_per_child=100,
    timezone="UTC",
    beat_schedule={
        "fill-empty-tours": {
            "task": "tours.fill_empty",
            "schedule": settings.FILL_TOURS_INTERVAL,
        },
        "fill-points": {
            "task": "points.fill",
            "schedule": crontab(hour=settings.FILL_POINTS_HOUR, minute=0),
        },
        "sync-tours-players": {
            "task": "tours.sync_players",
            "schedule": crontab(hour=settings.SYNC_TOURS_HOUR, minute=0),
        },
        "search-tours": {
            "task": "tours.search",
            "schedule": crontab(hour=settings.SEARCH_TOURS_HOUR, minute=0),
        },
        "fill-matches": {
            "task": "matches.fill_all",
            "schedule": crontab(hour=settings.FILL_MATCHES_HOUR, minute=0),
        },
    },
)


@worker_process_init.connect
def reset_db_pool(**_: object) -> None:
    """Сбросить пул подключений, унаследованный от родительского процесса при форке."""
    engine.sync_engine.dispose(close=False)


def run_async(coro: Coroutine) -> None:
    """Выполнить корутину в задаче celery и закрыть пул подключений за собой."""

    async def runner() -> None:
        try:
            await coro
        finally:
            # пул привязан к текущему event loop, следующая задача создаст свой
            await engine.dispose()

    asyncio.run(runner())
