from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    PlayerMatchRead,
    PlayerPointRead,
    RatingRefreshRead,
    ToursRefreshRead,
)
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


@router.post(
    "/tours/refresh",
    response_model=ToursRefreshRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_tours(session: SessionDep) -> ToursRefreshRead:
    """Обновить сведения о сыгранных турнирах у всех игроков.

    На каждого игрока ставится отдельная задача: она перезапрашивает его
    карточку в текущем рейтинг-листе и переписывает места и очки за турниры
    последнего года, попутно заводя незнакомые турниры. Ответ приходит сразу,
    работа идёт в фоне.
    """
    return await PlayersService.refresh_tours(session)


@router.get("/{player_id}/points", response_model=list[PlayerPointRead])
async def get_points(player_id: int, session: SessionDep) -> list[PlayerPointRead]:
    """История рейтинга игрока: по записи на месяц, от старых к новым."""
    return await PlayersService.get_points(session, player_id)


@router.get("/{player_id}/matches", response_model=list[PlayerMatchRead])
async def get_matches(
    player_id: int,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50, description="Сколько матчей вернуть")] = 5,
) -> list[PlayerMatchRead]:
    """Последние матчи игрока: свежие сверху, счёт — с его стороны."""
    return await PlayersService.get_matches(session, player_id, limit)
