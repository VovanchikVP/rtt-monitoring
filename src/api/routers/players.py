from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import RatingRefreshRead
from src.models.base import get_session
from src.service import PlayersService

router = APIRouter(prefix="/players", tags=["players"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/rating/refresh",
    response_model=RatingRefreshRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_rating(session: SessionDep) -> RatingRefreshRead:
    """Обновить историю рейтинга всех игроков.

    На каждого игрока ставится отдельная задача: она смотрит, за какие месяцы
    записей нет, и запрашивает внешнее API только по ним. Ответ приходит сразу,
    работа идёт в фоне.
    """
    return await PlayersService.refresh_rating(session)
