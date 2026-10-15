import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from celery import chain
from src.api.schemas import TourCreate, TourListRead, TourPlayerRead, TourRead
from src.celery.tasks import fill_empty_tours_task, fill_points_task
from src.models import Players, Points, Tours, tours_players
from src.models.base import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tours", tags=["tours"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[TourListRead])
async def get_tours(session: SessionDep) -> list[TourListRead]:
    """Список отслеживаемых турниров, ближайшие сверху."""
    players_count = (
        select(func.count())
        .select_from(tours_players)
        .where(tours_players.c.tour_id == Tours.id)
        .scalar_subquery()
        .label("players_count")
    )

    rows = await session.execute(
        select(
            Tours.id,
            Tours.name,
            Tours.location,
            Tours.begin_date,
            Tours.end_date,
            players_count,
        ).order_by(Tours.begin_date.asc().nulls_last(), Tours.id)
    )
    return [TourListRead.model_validate(row) for row in rows]


@router.post("", response_model=TourRead, status_code=status.HTTP_201_CREATED)
async def create_tour(
    payload: TourCreate,
    session: SessionDep,
) -> Tours:
    """Создать турнир по его id.

    Запись создаётся пустой, остальные поля дозаполняет задача celery.
    """
    exists = await session.scalar(select(Tours).where(Tours.id == payload.id))
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Турнир {payload.id} уже существует",
        )

    tour = Tours(id=payload.id)
    session.add(tour)
    await session.commit()
    await session.refresh(tour)

    # брокер может быть недоступен — тогда турнир заберёт периодическая задача
    try:
        # очки добираются сразу после заполнения турнира
        chain(fill_empty_tours_task.si(), fill_points_task.si()).delay()
    except Exception:
        logger.exception("Не удалось поставить задачу заполнения турнира %s", payload.id)

    return tour


def get_age(birth_date: date | None) -> int | None:
    """Полных лет на сегодня."""
    if birth_date is None:
        return None
    today = date.today()
    return (
        today.year
        - birth_date.year
        - ((today.month, today.day) < (birth_date.month, birth_date.day))
    )


@router.delete("/{tour_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tour(tour_id: int, session: SessionDep) -> None:
    """Удалить турнир и его связи с игроками. Сами игроки остаются."""
    tour = await session.get(Tours, tour_id)
    if tour is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Турнир {tour_id} не найден",
        )

    links = await session.execute(delete(tours_players).where(tours_players.c.tour_id == tour_id))
    await session.delete(tour)
    await session.commit()

    logger.info("Турнир %s удалён, снято связей с игроками: %s", tour_id, links.rowcount)


@router.get("/{tour_id}/players", response_model=list[TourPlayerRead])
async def get_tour_players(tour_id: int, session: SessionDep) -> list[TourPlayerRead]:
    """Актуальный список участников турнира, от большего числа очков к меньшему."""
    tour = await session.get(Tours, tour_id)
    if tour is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Турнир {tour_id} не найден",
        )

    # последняя по дате запись об очках каждого игрока
    last_points = (
        select(Points.players_id, Points.points)
        .distinct(Points.players_id)
        .order_by(Points.players_id, Points.date.desc())
        .subquery()
    )
    points = func.coalesce(last_points.c.points, 0).label("points")

    rows = await session.execute(
        select(Players.id, Players.name, Players.birth_date, Players.city, points)
        .join(tours_players, tours_players.c.player_id == Players.id)
        .outerjoin(last_points, last_points.c.players_id == Players.id)
        .where(tours_players.c.tour_id == tour_id)
        .order_by(points.desc(), Players.name)
    )

    return [
        TourPlayerRead(
            number=number,
            id=row.id,
            name=row.name,
            age=get_age(row.birth_date),
            city=row.city,
            points=row.points,
        )
        for number, row in enumerate(rows, start=1)
    ]
