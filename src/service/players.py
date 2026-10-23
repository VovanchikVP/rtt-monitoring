import logging
import re

from fastapi import HTTPException, status
from sqlalchemy import Row, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.api.schemas import (
    PlayerMatchRead,
    PlayerPointRead,
    RatingRefreshRead,
    ToursRefreshRead,
)
from src.celery.service.fill_rating_history import FillRatingHistoryService
from src.celery.tasks import fill_player_tours_task, fill_rating_history_task
from src.models import Matches, Players, Points
from src.service.queue import schedule_each

logger = logging.getLogger(__name__)


class PlayersService:
    """Бизнес-логика эндпоинтов игроков."""

    # счёт сета — «6-4», иногда с тай-брейком — «7-6(5)»
    SET_SCORE = re.compile(r"^(\d+)-(\d+)(.*)$")
    # в базе сеты разделены так, как их отдало API: где запятой, где пробелом
    SET_SPLIT = re.compile(r"[,\s]+")

    @classmethod
    async def get_points(cls, session: AsyncSession, player_id: int) -> list[PlayerPointRead]:
        """История рейтинга игрока, от старых записей к новым."""
        await cls.get_player(session, player_id)

        rows = await session.execute(
            select(Points.date, Points.points)
            .where(Points.players_id == player_id)
            .order_by(Points.date)
        )
        return [PlayerPointRead.model_validate(row) for row in rows]

    @classmethod
    async def get_matches(
        cls, session: AsyncSession, player_id: int, limit: int
    ) -> list[PlayerMatchRead]:
        """Последние матчи игрока, свежие сверху.

        Счёт в базе записан со стороны первого игрока матча; здесь он
        разворачивается так, чтобы читаться со стороны запрошенного.
        """
        await cls.get_player(session, player_id)

        rival = aliased(Players)
        # соперник — тот из двоих, кем игрок не является
        rival_id = case(
            (Matches.first_player_id == player_id, Matches.second_player_id),
            else_=Matches.first_player_id,
        )
        rows = await session.execute(
            select(
                Matches.date,
                rival.name.label("opponent"),
                Matches.first_player_id,
                Matches.first_score,
                Matches.second_score,
                Matches.score,
                Matches.winner_player_id,
            )
            .join(rival, rival.id == rival_id)
            .where(
                or_(
                    Matches.first_player_id == player_id,
                    Matches.second_player_id == player_id,
                )
            )
            # даты может не быть, такие матчи уходят в конец
            .order_by(Matches.date.desc().nulls_last(), Matches.id)
            .limit(limit)
        )
        return [cls.as_player_match(row, player_id) for row in rows]

    @classmethod
    def as_player_match(cls, row: Row, player_id: int) -> PlayerMatchRead:
        """Строка выборки матчей — в плашку для фронта."""
        # игрок записан в матче первым, значит счёт уже с его стороны
        mine = row.first_player_id == player_id
        return PlayerMatchRead(
            date=row.date,
            opponent=row.opponent,
            sets=cls.sets_score(row.first_score, row.second_score, mine),
            games=cls.games_score(row.score, mine),
            won=None if row.winner_player_id is None else row.winner_player_id == player_id,
        )

    @classmethod
    def sets_score(cls, first: int | None, second: int | None, mine: bool) -> str | None:
        """Счёт по сетам «2-1»; None, пока сеты не посчитаны."""
        if first is None or second is None:
            return None
        return f"{first}-{second}" if mine else f"{second}-{first}"

    @classmethod
    def games_score(cls, score: str | None, mine: bool) -> str | None:
        """Счёт по геймам «6-4 3-6 7-5»; при `mine=False` разворачивается.

        Разделитель сетов приводится к пробелу: наружу счёт выглядит
        одинаково, из какого бы источника он ни пришёл.
        """
        if not score:
            return None

        sets = [part for part in cls.SET_SPLIT.split(score.strip()) if part]
        if not mine:
            # сет непонятного вида оставляем как есть — лучше так, чем потерять
            sets = [cls.SET_SCORE.sub(r"\2-\1\3", part) for part in sets]
        return " ".join(sets) or None

    @classmethod
    async def get_player(cls, session: AsyncSession, player_id: int) -> Players:
        """Игрок из базы; 404, если такого нет."""
        player = await session.get(Players, player_id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Игрок {player_id} не найден",
            )
        return player

    @classmethod
    async def refresh_rating(cls, session: AsyncSession) -> RatingRefreshRead:
        """Поставить задачу добора истории рейтинга на каждого игрока в базе."""
        player_ids = list(await session.scalars(select(Players.id).order_by(Players.id)))
        if not player_ids:
            logger.info("Обновление рейтинга: игроков в базе нет")
            return RatingRefreshRead(players=0, queued=0, months=FillRatingHistoryService.MONTHS)

        schedule_each(fill_rating_history_task, player_ids)
        logger.info("Обновление рейтинга: поставлено задач %s", len(player_ids))
        return RatingRefreshRead(
            players=len(player_ids),
            queued=len(player_ids),
            months=FillRatingHistoryService.MONTHS,
        )

    @classmethod
    async def refresh_tours(cls, session: AsyncSession) -> ToursRefreshRead:
        """Поставить задачу обновления сыгранных турниров на каждого игрока.

        Задача перезапрашивает карточку игрока в текущем рейтинг-листе и
        переписывает его результаты: места и очки за турнир пересчитываются,
        а фоновые задачи дотягивают только то, чего в базе ещё нет.
        """
        player_ids = list(await session.scalars(select(Players.id).order_by(Players.id)))
        if not player_ids:
            logger.info("Обновление турниров: игроков в базе нет")
            return ToursRefreshRead(players=0, queued=0)

        schedule_each(fill_player_tours_task, player_ids)
        logger.info("Обновление турниров: поставлено задач %s", len(player_ids))
        return ToursRefreshRead(players=len(player_ids), queued=len(player_ids))
