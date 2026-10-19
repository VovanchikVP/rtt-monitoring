import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import RatingRefreshRead
from src.celery.service.fill_rating_history import FillRatingHistoryService
from src.celery.tasks import fill_rating_history_task
from src.const import REQUEST_DELAY
from src.models import Players

logger = logging.getLogger(__name__)


class PlayersService:
    """Бизнес-логика эндпоинтов игроков."""

    @classmethod
    async def refresh_rating(cls, session: AsyncSession) -> RatingRefreshRead:
        """Поставить задачу добора истории рейтинга на каждого игрока в базе."""
        player_ids = list(await session.scalars(select(Players.id).order_by(Players.id)))
        if not player_ids:
            logger.info("Обновление рейтинга: игроков в базе нет")
            return RatingRefreshRead(players=0, queued=0, months=FillRatingHistoryService.MONTHS)

        cls.schedule_history(player_ids)
        logger.info("Обновление рейтинга: поставлено задач %s", len(player_ids))
        return RatingRefreshRead(
            players=len(player_ids),
            queued=len(player_ids),
            months=FillRatingHistoryService.MONTHS,
        )

    @classmethod
    def schedule_history(cls, player_ids: list[int]) -> None:
        """Поставить задачи в очередь с шагом `REQUEST_DELAY` между ними."""
        try:
            for number, player_id in enumerate(player_ids):
                # задачи расходятся по времени ещё на входе в очередь,
                # rate_limit самой задачи страхует от наплыва
                fill_rating_history_task.apply_async(
                    args=[player_id], countdown=number * REQUEST_DELAY
                )
        except Exception as error:
            # периодической задачи на этот случай нет, молчать нельзя
            logger.exception("Не удалось поставить задачи обновления рейтинга")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Очередь задач недоступна, попробуйте позже",
            ) from error
