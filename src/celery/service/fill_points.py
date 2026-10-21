import logging
import time
from datetime import date

import aiohttp
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.celery.service.dates import parse_date
from src.const import API_URL, HEADERS, HTTP_TIMEOUT
from src.models import Players, Points, RatingDetails, Tours
from src.models.base import async_session

logger = logging.getLogger(__name__)


class FillPointsService:
    """Наполнение таблицы `points` рейтинговыми очками игроков.

    Запрашивает данные только по тем игрокам, у которых ещё нет записи
    за текущий месяц. Новые записи добавляются, старые не трогаются.

    Тот же ответ несёт список турниров игрока — он ложится в `rating_details`,
    а незнакомые турниры попутно заводятся в `tours`.
    """

    @classmethod
    async def run(cls) -> None:
        """Добрать очки по всем игрокам без записи за текущий месяц."""
        player_ids = await cls.get_players_without_points()
        if not player_ids:
            logger.info("Очки за текущий месяц есть у всех игроков")
            return

        logger.info("Игроков без очков за текущий месяц: %s", len(player_ids))
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        added = 0
        async with aiohttp.ClientSession(timeout=timeout) as http:
            for player_id in player_ids:
                try:
                    added += await cls.fill_points(http, player_id)
                except Exception:
                    # один сбойный игрок не должен ронять остальных
                    logger.exception("Не удалось получить очки игрока %s", player_id)

        logger.info("Добавлено записей об очках: %s", added)

    @classmethod
    async def get_players_without_points(cls) -> list[int]:
        """Игроки, по которым в текущем месяце ещё нет записи об очках."""
        month_start = date.today().replace(day=1)
        with_points = select(Points.players_id).where(Points.date >= month_start)
        async with async_session() as session:
            return list(
                await session.scalars(select(Players.id).where(Players.id.notin_(with_points)))
            )

    @classmethod
    async def fill_points(cls, http: aiohttp.ClientSession, player_id: int) -> int:
        """Запросить очки игрока и добавить запись. Возвращает число добавленных записей."""
        data = await cls.fetch_rating_details(http, player_id)
        points = cls.get_points(data)

        async with async_session() as session:
            # параллельный запуск задачи мог успеть записать очки раньше
            result = await session.execute(
                insert(Points)
                .values(players_id=player_id, date=date.today(), points=points)
                .on_conflict_do_nothing(index_elements=["players_id", "date"])
            )
            await session.commit()

        await cls.save_rating_details(player_id, cls.get_tours(data))

        return result.rowcount

    @classmethod
    async def fetch_rating_details(
        cls, http: aiohttp.ClientSession, player_id: int, rating_id: str | None = None
    ) -> dict:
        """Запросить карточку игрока в рейтинг-листе; по умолчанию — в текущем."""
        form = [
            # ruid — метка времени в миллисекундах, как её шлёт браузер
            ("ruid", str(int(time.time() * 1000))),
            ("method[0]", "rating.details"),
            ("rating_id", rating_id or cls.get_rating_id()),
            ("player_id", str(player_id)),
        ]
        async with http.post(API_URL, data=form, headers=HEADERS) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    @classmethod
    def get_rating_id(cls, month: date | None = None) -> str:
        """Идентификатор рейтинг-листа месяца; без аргумента — текущего."""
        return (month or date.today()).strftime("%Y%m011")

    @classmethod
    def get_points(cls, data: dict) -> int:
        """Очки игрока из ответа `rating.details`; без рейтинга считаем 0."""
        rating = data.get("data", {}).get("rating.details", {}).get("rating") or {}
        return rating.get("points") or 0

    @classmethod
    def get_tours(cls, data: dict) -> list[dict]:
        """Результаты игрока по турнирам из ответа `rating.details`.

        Один турнир в списке встречается один раз, но ответы соседних месяцев
        пересекаются, поэтому записи дедуплицируются по `tour_id`.
        """
        tours = data.get("data", {}).get("rating.details", {}).get("tours") or []
        parsed = {
            tour["tour_id"]: {
                "tour_id": tour["tour_id"],
                "name": tour.get("name"),
                "city": tour.get("city") or None,
                # у турнира в этом блоке одна дата — она же начало и конец
                "date": parse_date(tour.get("date")),
                # место бывает диапазоном вида «17-32», поэтому строка
                "position": str(tour["pos"]) if tour.get("pos") not in (None, "") else None,
                "points": tour.get("points"),
            }
            for tour in tours
            if tour.get("tour_id")
        }
        return list(parsed.values())

    @classmethod
    async def save_rating_details(cls, player_id: int, tours: list[dict]) -> int:
        """Завести недостающие турниры и записать результаты игрока в них.

        Возвращает число затронутых записей `rating_details`.
        """
        if not tours:
            return 0

        async with async_session() as session:
            # турнира может не быть в базе: внешний ключ требует завести его первым
            await session.execute(
                insert(Tours)
                .values(
                    [
                        {
                            "id": tour["tour_id"],
                            "name": tour["name"],
                            "location": tour["city"],
                            "begin_date": tour["date"],
                            "end_date": tour["date"],
                        }
                        for tour in tours
                    ]
                )
                # знакомый турнир не трогаем: его карточка заполнена подробнее
                .on_conflict_do_nothing(index_elements=["id"])
            )

            statement = insert(RatingDetails).values(
                [
                    {
                        "tour_id": tour["tour_id"],
                        "player_id": player_id,
                        "position": tour["position"],
                        "points": tour["points"],
                    }
                    for tour in tours
                ]
            )
            # очки за турнир со временем пересчитываются — свежий ответ главнее
            result = await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["tour_id", "player_id"],
                    set_={
                        "position": statement.excluded.position,
                        "points": statement.excluded.points,
                    },
                )
            )
            await session.commit()

        return result.rowcount
