import logging
from datetime import date

import aiohttp
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.celery.service.api import ThrottledError
from src.celery.service.fill_rating_history import FillRatingHistoryService
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
        new_players: list[int] = []
        async with aiohttp.ClientSession(timeout=timeout) as http:
            for tour_id in tour_ids:
                try:
                    new_players += await cls.sync_tour(http, tour_id)
                except ThrottledError:
                    # следующий турнир упрётся в ту же проверку — откладываем задачу
                    raise
                except Exception:
                    # один сбойный турнир не должен ронять остальные
                    logger.exception("Не удалось сверить состав турнира %s", tour_id)

        # по новым игрокам сразу добираем историю рейтинга за последние месяцы,
        # не дожидаясь суточного запуска
        FillRatingHistoryService.schedule(new_players)

    @classmethod
    async def get_upcoming_tour_ids(cls) -> list[int]:
        """Турниры, которые ещё не начались."""
        async with async_session() as session:
            return list(
                await session.scalars(select(Tours.id).where(Tours.begin_date > date.today()))
            )

    @classmethod
    async def sync_tour(cls, http: aiohttp.ClientSession, tour_id: int) -> list[int]:
        """Сверить состав одного турнира. Возвращает идентификаторы добавленных игроков."""
        data = await FillToursService.fetch_tour_players(http, tour_id)
        players = FillToursService.get_tour_players(data)
        player_ids = [p["id"] for p in players]

        async with async_session() as session:
            new_players = await FillToursService.add_missing_players(session, players)
            await FillToursService.add_missing_links(session, tour_id, player_ids)
            await cls.remove_extra_links(session, tour_id, player_ids)
            await session.commit()

        logger.info("Состав турнира %s сверен, участников: %s", tour_id, len(player_ids))
        return new_players

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
