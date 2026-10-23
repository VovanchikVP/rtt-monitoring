from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    MatchesRefreshRead,
    TourCreate,
    TourListRead,
    TourPageRead,
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
    """Отслеживаемые турниры — те, что ещё не закончились; ближайшие сверху."""
    return await ToursService.get_tours(session)


@router.get("/finished", response_model=TourPageRead)
async def get_finished_tours(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100, description="Сколько турниров вернуть")] = 10,
    offset: Annotated[int, Query(ge=0, description="Сколько турниров пропустить")] = 0,
) -> TourPageRead:
    """Страница завершённых турниров, от поздней даты окончания к ранней.

    Вместе со страницей приходит общее число завершённых турниров в базе.
    """
    return await ToursService.get_finished_tours(session, limit, offset)


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
