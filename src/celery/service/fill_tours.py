import logging
import time

import aiohttp
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.celery.service.dates import parse_date
from src.celery.service.fill_rating_history import FillRatingHistoryService
from src.celery.service.response import get_node
from src.const import API_URL, HEADERS, HTTP_TIMEOUT
from src.models import Players, Tours, tours_players
from src.models.base import async_session

logger = logging.getLogger(__name__)


class FillToursService:
    """Заполнение турниров данными внешнего API.

    Находит в `tours` незаполненные записи, дотягивает по ним карточку турнира,
    добавляет недостающих игроков и связи игроков с турниром.
    """

    @classmethod
    async def run(cls) -> None:
        """Обработать все незаполненные турниры."""
        tour_ids = await cls.get_empty_tour_ids()
        if not tour_ids:
            logger.info("Незаполненных турниров нет")
            return

        logger.info("Незаполненных турниров: %s", len(tour_ids))
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            for tour_id in tour_ids:
                try:
                    await cls.fill_tour(http, tour_id)
                except Exception:
                    # один сбойный турнир не должен ронять остальные
                    logger.exception("Не удалось заполнить турнир %s", tour_id)

    @classmethod
    async def get_empty_tour_ids(cls) -> list[int]:
        """Идентификаторы турниров, по которым ещё нет данных."""
        async with async_session() as session:
            return list(await session.scalars(select(Tours.id).where(Tours.name.is_(None))))

    @classmethod
    async def fill_tour(cls, http: aiohttp.ClientSession, tour_id: int) -> None:
        """Заполнить карточку турнира, добавить недостающих игроков и связи с турниром."""
        data = await cls.fetch_tour_players(http, tour_id)

        async with async_session() as session:
            tour = await session.get(Tours, tour_id)
            if tour is None:
                logger.warning("Турнир %s исчез из базы, пропускаем", tour_id)
                return

            for field, value in cls.get_tour_main(data).items():
                setattr(tour, field, value)

            players = cls.get_tour_players(data)
            new_players = await cls.add_missing_players(session, players)
            await cls.add_missing_links(session, tour_id, [p["id"] for p in players])

            await session.commit()

        logger.info("Турнир %s заполнен, участников: %s", tour_id, len(players))

        # по новым игрокам сразу добираем историю рейтинга за последние месяцы,
        # не дожидаясь суточного запуска
        FillRatingHistoryService.schedule(new_players)

    @classmethod
    async def fetch_tour_players(cls, http: aiohttp.ClientSession, tour_id: int) -> dict:
        """Запросить карточку турнира вместе со списком участников."""
        form = [
            # ruid — метка времени в миллисекундах, как её шлёт браузер
            ("ruid", str(int(time.time() * 1000))),
            ("method[0]", "tour.card.main"),
            ("tour_id", str(tour_id)),
            ("part[0]", "players"),
        ]
        async with http.post(API_URL, data=form, headers=HEADERS) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    @classmethod
    def get_tour_main(cls, data: dict) -> dict:
        """Основные поля карточки турнира из ответа `tour.card.main`."""
        tour = get_node(data, "tour.card.main")
        return {
            "name": tour.get("name"),
            "location": tour.get("location"),
            "location_full": tour.get("location_full"),
            "begin_date": parse_date(tour.get("begin_date")),
            "end_date": parse_date(tour.get("end_date")),
            "tour_members": tour.get("tour_members"),
        }

    @classmethod
    def get_tour_players(cls, data: dict, exclude_left: bool = True) -> list[dict]:
        """Участники турнира в виде полей таблицы `players`."""
        players = get_node(data, "tour.card.main").get("players") or []
        return [
            {
                "id": p.get("player_id"),
                "name": p.get("name"),
                "birth_date": parse_date(p.get("birth_date")),
                "city": p.get("doc_city") or None,
            }
            for p in players
            if p.get("player_id") and not (exclude_left and p.get("leave"))
        ]

    @classmethod
    async def add_missing_players(cls, session: AsyncSession, players: list[dict]) -> list[int]:
        """Добавить в `players` тех, кого там ещё нет. Возвращает их идентификаторы."""
        if not players:
            return []

        known = set(
            await session.scalars(
                select(Players.id).where(Players.id.in_([p["id"] for p in players]))
            )
        )
        new = [p for p in players if p["id"] not in known]
        if not new:
            return []

        await session.execute(insert(Players).values(new).on_conflict_do_nothing())
        logger.info("Добавлено новых игроков: %s", len(new))
        return [p["id"] for p in new]

    @classmethod
    async def add_missing_links(
        cls, session: AsyncSession, tour_id: int, player_ids: list[int]
    ) -> None:
        """Добавить недостающие связи игроков с турниром."""
        if not player_ids:
            return

        linked = set(
            await session.scalars(
                select(tours_players.c.player_id).where(tours_players.c.tour_id == tour_id)
            )
        )
        new = [{"tour_id": tour_id, "player_id": pid} for pid in player_ids if pid not in linked]
        if not new:
            return

        await session.execute(insert(tours_players).values(new).on_conflict_do_nothing())
        logger.info("Добавлено связей турнир-игрок: %s", len(new))
