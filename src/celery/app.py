import asyncio
from collections.abc import Coroutine

from celery import Celery
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
