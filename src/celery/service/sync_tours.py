import logging
from datetime import date

import aiohttp
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.celery.app import celery_app
from src.celery.service.fill_tours import FillToursService
from src.const import HTTP_TIMEOUT
from src.models import Tours, tours_players
from src.models.base import async_session

logger = logging.getLogger(__name__)


class SyncToursService:
    """Синхронизация составов предстоящих турниров.

    По турнирам, которые ещё не начались, сверяет список участников с внешним API:
    добавляет недостающих игроков и связи, удаляет связи тех, кого в заявке больше нет.
    Сами записи игроков при этом остаются.
    """

    @classmethod
    async def run(cls) -> None:
        """Сверить составы всех предстоящих турниров."""
        tour_ids = await cls.get_upcoming_tour_ids()
        if not tour_ids:
            logger.info("Предстоящих турниров нет")
            return

        logger.info("Предстоящих турниров: %s", len(tour_ids))
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        added_players = 0
        async with aiohttp.ClientSession(timeout=timeout) as http:
            for tour_id in tour_ids:
                try:
                    added_players += await cls.sync_tour(http, tour_id)
                except Exception:
                    # один сбойный турнир не должен ронять остальные
                    logger.exception("Не удалось сверить состав турнира %s", tour_id)

        if added_players:
            # по новым игрокам сразу добираем очки, не дожидаясь суточного запуска
            celery_app.send_task("points.fill")

    @classmethod
    async def get_upcoming_tour_ids(cls) -> list[int]:
        """Турниры, которые ещё не начались."""
        async with async_session() as session:
            return list(
                await session.scalars(select(Tours.id).where(Tours.begin_date > date.today()))
            )

    @classmethod
    async def sync_tour(cls, http: aiohttp.ClientSession, tour_id: int) -> int:
        """Сверить состав одного турнира. Возвращает число добавленных игроков."""
        data = await FillToursService.fetch_tour_players(http, tour_id)
        players = FillToursService.get_tour_players(data)
        player_ids = [p["id"] for p in players]

        async with async_session() as session:
            added = await FillToursService.add_missing_players(session, players)
            await FillToursService.add_missing_links(session, tour_id, player_ids)
            await cls.remove_extra_links(session, tour_id, player_ids)
            await session.commit()

        logger.info("Состав турнира %s сверен, участников: %s", tour_id, len(player_ids))
        return added

    @classmethod
    async def remove_extra_links(
        cls, session: AsyncSession, tour_id: int, player_ids: list[int]
    ) -> None:
        """Убрать связи с игроками, которых больше нет в заявке турнира.

        Записи самих игроков не удаляются — они могут участвовать в других турнирах.
        """
        linked = set(
            await session.scalars(
                select(tours_players.c.player_id).where(tours_players.c.tour_id == tour_id)
            )
        )
        extra = linked - set(player_ids)
        if not extra:
            return

        await session.execute(
            delete(tours_players).where(
                tours_players.c.tour_id == tour_id,
                tours_players.c.player_id.in_(extra),
            )
        )
        logger.info("Удалено лишних связей турнир-игрок: %s", len(extra))
