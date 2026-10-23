from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    MatchesRefreshRead,
    TourCreate,
    TourListRead,
    TourPlayerRead,
    TourRead,
)
from src.models import Tours
from src.models.base import get_session
from src.service import ToursService

router = APIRouter(prefix="/tours", tags=["tours"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[TourListRead])
async def get_tours(session: SessionDep) -> list[TourListRead]:
    """Список отслеживаемых турниров, ближайшие сверху."""
    return await ToursService.get_tours(session)


@router.post("", response_model=TourRead, status_code=status.HTTP_201_CREATED)
async def create_tour(payload: TourCreate, session: SessionDep) -> Tours:
    """Создать турнир по его id.

    Запись создаётся пустой, остальные поля дозаполняет задача celery.
    """
    return await ToursService.create_tour(session, payload)


@router.post(
    "/matches/refresh",
    response_model=MatchesRefreshRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_matches(session: SessionDep) -> MatchesRefreshRead:
    """Принудительно обновить матчи во всех турнирах.

    На каждый турнир ставится отдельная задача: она перезапрашивает карточку
    вместе с сеткой и переписывает матчи турнира целиком, попутно освежая
    его даты, место и признак завершённости. В отличие от суточной задачи
    даты и `is_finished` не ограничивают выбор — берутся все турниры базы.

    Ответ приходит сразу, работа идёт в фоне: запросы к внешнему API
    разводятся по времени, так что на большой базе обход займёт часы.
    """
    return await ToursService.refresh_matches(session)


@router.delete("/{tour_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tour(tour_id: int, session: SessionDep) -> None:
    """Удалить турнир и его связи с игроками. Сами игроки остаются."""
    await ToursService.delete_tour(session, tour_id)


@router.get("/{tour_id}/players", response_model=list[TourPlayerRead])
async def get_tour_players(tour_id: int, session: SessionDep) -> list[TourPlayerRead]:
    """Актуальный список участников турнира, от большего числа очков к меньшему."""
    return await ToursService.get_tour_players(session, tour_id)
