import logging
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from celery import chain
from src.api.schemas import TourCreate, TourListRead, TourPlayerRead
from src.celery.tasks import fill_empty_tours_task, fill_points_task
from src.models import Players, Points, Tours, tours_players

logger = logging.getLogger(__name__)


class ToursService:
    """Бизнес-логика эндпоинтов турниров."""

    @classmethod
    async def get_tours(cls, session: AsyncSession) -> list[TourListRead]:
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

    @classmethod
    async def create_tour(cls, session: AsyncSession, payload: TourCreate) -> Tours:
        """Создать пустую запись турнира и поставить задачу на её заполнение."""
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

        cls.schedule_fill(payload.id)
        return tour

    @classmethod
    def schedule_fill(cls, tour_id: int) -> None:
        """Поставить в очередь заполнение турнира и следом добор очков."""
        # брокер может быть недоступен — тогда турнир заберёт периодическая задача
        try:
            chain(fill_empty_tours_task.si(), fill_points_task.si()).delay()
        except Exception:
            logger.exception("Не удалось поставить задачу заполнения турнира %s", tour_id)

    @classmethod
    async def delete_tour(cls, session: AsyncSession, tour_id: int) -> None:
        """Удалить турнир и его связи с игроками. Сами игроки остаются."""
        tour = await cls.get_tour_or_404(session, tour_id)

        links = await session.execute(
            delete(tours_players).where(tours_players.c.tour_id == tour_id)
        )
        await session.delete(tour)
        await session.commit()

        logger.info("Турнир %s удалён, снято связей с игроками: %s", tour_id, links.rowcount)

    @classmethod
    async def get_tour_players(cls, session: AsyncSession, tour_id: int) -> list[TourPlayerRead]:
        """Актуальный список участников турнира, от большего числа очков к меньшему."""
        await cls.get_tour_or_404(session, tour_id)

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
                age=cls.get_age(row.birth_date),
                city=row.city,
                points=row.points,
            )
            for number, row in enumerate(rows, start=1)
        ]

    @classmethod
    async def get_tour_or_404(cls, session: AsyncSession, tour_id: int) -> Tours:
        """Турнир из базы либо 404."""
        tour = await session.get(Tours, tour_id)
        if tour is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Турнир {tour_id} не найден",
            )
        return tour

    @classmethod
    def get_age(cls, birth_date: date | None) -> int | None:
        """Полных лет на сегодня."""
        if birth_date is None:
            return None
        today = date.today()
        return (
            today.year
            - birth_date.year
            - ((today.month, today.day) < (birth_date.month, birth_date.day))
        )
