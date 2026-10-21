import asyncio
import logging
from collections.abc import Iterable
from datetime import date

import aiohttp
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.celery.app import celery_app
from src.celery.service.fill_points import FillPointsService
from src.const import HTTP_TIMEOUT, REQUEST_DELAY
from src.models import Points
from src.models.base import async_session

logger = logging.getLogger(__name__)


class FillRatingHistoryService:
    """История рейтинга одного игрока за последние месяцы.

    Задача работает по одному игроку: смотрит, за какие месяцы записи об очках
    уже есть, и запрашивает внешнее API только по недостающим. Между запросами
    выдерживается пауза `REQUEST_DELAY`.

    Запись месяца датируется его первым числом, поэтому повторный запуск
    ничего не запрашивает заново, а ежемесячная задача `points.fill` видит
    такой месяц заполненным.
    """

    # глубина истории, месяцы (текущий месяц и одиннадцать предыдущих)
    MONTHS = 12

    # не чаще одного запуска в REQUEST_DELAY секунд на воркера
    RATE_LIMIT = f"{60 // REQUEST_DELAY}/m"

    @classmethod
    def schedule(cls, player_ids: list[int]) -> None:
        """Поставить задачу добора истории рейтинга на каждого игрока из списка.

        Задачи расходятся по времени ещё на входе в очередь, `rate_limit`
        самой задачи страхует от наплыва.
        """
        if not player_ids:
            return

        for number, player_id in enumerate(player_ids):
            celery_app.send_task(
                "points.fill_history", args=[player_id], countdown=number * REQUEST_DELAY
            )
        logger.info("Поставлено задач на историю рейтинга: %s", len(player_ids))

    @classmethod
    async def run(cls, player_id: int) -> int:
        """Добрать недостающие месяцы рейтинга игрока. Возвращает число добавленных записей."""
        months = cls.get_months()
        missing = await cls.get_missing_months(player_id, months)
        if not missing:
            logger.info("Игрок %s: история рейтинга заполнена", player_id)
            return 0

        logger.info("Игрок %s: месяцев без рейтинга %s", player_id, len(missing))
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            points, tours = await cls.collect(http, player_id, missing)

        added = await cls.add_points(player_id, points) if points else 0
        details = await FillPointsService.save_rating_details(player_id, tours)
        logger.info(
            "Игрок %s: добавлено записей рейтинга %s, результатов турниров %s",
            player_id,
            added,
            details,
        )
        return added

    @classmethod
    def get_months(cls) -> list[date]:
        """Первые числа последних `MONTHS` месяцев, от старого к новому."""
        current = date.today().replace(day=1)
        months = []
        for shift in range(cls.MONTHS):
            month = current.month - shift
            year = current.year + (month - 1) // 12
            months.append(date(year, (month - 1) % 12 + 1, 1))
        return list(reversed(months))

    @classmethod
    async def get_missing_months(cls, player_id: int, months: list[date]) -> list[date]:
        """Месяцы из `months`, по которым у игрока ещё нет записи об очках."""
        async with async_session() as session:
            dates = await session.scalars(
                select(Points.date).where(
                    Points.players_id == player_id,
                    Points.date >= months[0],
                )
            )
            return cls.filter_missing(months, dates)

    @classmethod
    def filter_missing(cls, months: list[date], dates: Iterable[date]) -> list[date]:
        """Отсеять месяцы, в которых уже есть хотя бы одна запись.

        Запись за месяц может быть датирована любым его числом: ежемесячная
        задача пишет сегодняшнюю дату, эта — первое число.
        """
        filled = {(value.year, value.month) for value in dates}
        return [month for month in months if (month.year, month.month) not in filled]

    @classmethod
    async def collect(
        cls, http: aiohttp.ClientSession, player_id: int, months: list[date]
    ) -> tuple[dict[date, int], list[dict]]:
        """Запросить каждый месяц, выдерживая паузу между запросами.

        Возвращает очки по месяцам и результаты по турнирам. Списки турниров
        соседних месяцев пересекаются, а очки за турнир со временем
        пересчитываются: месяцы идут от старых к новым, поэтому побеждает
        самый свежий ответ.

        Текущий месяц до публикации рейтинг-листа пропускается — см.
        `FillPointsService.is_rating_pending`.
        """
        points: dict[date, int] = {}
        tours: dict[int, dict] = {}
        today = date.today()
        for number, month in enumerate(months):
            if number:
                await cls.pause()
            try:
                data = await FillPointsService.fetch_rating_details(
                    http, player_id, FillPointsService.get_rating_id(month)
                )
            except Exception:
                # один сбойный месяц не должен ронять остальные
                logger.exception("Не удалось получить рейтинг игрока %s за %s", player_id, month)
                continue

            value = FillPointsService.get_points(data)
            if FillPointsService.is_rating_pending(month, value, today):
                # рейтинг-лист текущего месяца ещё не опубликован: ноль закрыл бы
                # месяц, и настоящие очки сюда уже не попали бы
                logger.info("Игрок %s: рейтинг за %s ещё не опубликован", player_id, month)
            else:
                points[month] = value

            for tour in FillPointsService.get_tours(data):
                tours[tour["tour_id"]] = tour

        return points, list(tours.values())

    @classmethod
    async def pause(cls) -> None:
        """Пауза между запросами: частых обращений внешнее API не прощает."""
        await asyncio.sleep(REQUEST_DELAY)

    @classmethod
    async def add_points(cls, player_id: int, points: dict[date, int]) -> int:
        """Добавить записи об очках. Возвращает число действительно добавленных."""
        async with async_session() as session:
            # параллельный запуск задачи мог успеть записать тот же месяц раньше
            result = await session.execute(
                insert(Points)
                .values(
                    [
                        {"players_id": player_id, "date": month, "points": value}
                        for month, value in sorted(points.items())
                    ]
                )
                .on_conflict_do_nothing(index_elements=["players_id", "date"])
            )
            await session.commit()

        return result.rowcount
