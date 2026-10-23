import calendar
import itertools
import logging
import time
from datetime import date

import aiohttp
from sqlalchemy.dialects.postgresql import insert

from src.celery.app import celery_app
from src.celery.service.response import get_node
from src.const import API_URL, HEADERS, HTTP_TIMEOUT
from src.models import SearchSettings, Tours
from src.models.base import async_session

logger = logging.getLogger(__name__)


class SearchToursService:
    """Поиск турниров во внешнем API по сохранённым в базе фильтрам.

    Запрашивает список турниров (метод API `tour.roster`) за период
    «сегодня + N месяцев» и отдаёт идентификаторы найденных турниров.
    Параметры поиска берутся из единственной строки таблицы `search_settings`.

    Внешнее API фильтрует по одному рангу и одной локации за запрос, поэтому
    по спискам рангов и локаций поиск идёт перебором всех их сочетаний.
    Найденные турниры, которых ещё нет в базе, ставятся на отслеживание.
    """

    # страховка от бесконечной постраничной выборки, если API врёт про page_max
    MAX_PAGES = 100

    @classmethod
    async def run(cls) -> None:
        """Найти турниры по сохранённым фильтрам и поставить новые на отслеживание."""
        tour_ids = await cls.get_tour_ids()
        if not tour_ids:
            logger.info("Поиск не дал турниров")
            return

        added = await cls.add_new_tours(tour_ids)
        logger.info("Поставлено на отслеживание новых турниров: %s", added)

        if added:
            try:
                # карточки новых турниров забираем сразу, не дожидаясь периодической задачи
                celery_app.send_task("tours.fill_empty")
            except Exception:
                # брокер может быть недоступен — турниры заберёт периодическая задача
                logger.exception("Не удалось поставить задачу заполнения новых турниров")

    @classmethod
    async def add_new_tours(cls, tour_ids: list[int]) -> int:
        """Завести пустые записи турниров, которых ещё нет. Возвращает число добавленных."""
        async with async_session() as session:
            result = await session.execute(
                insert(Tours)
                .values([{"id": tour_id} for tour_id in tour_ids])
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await session.commit()

        return result.rowcount

    @classmethod
    async def get_tour_ids(cls) -> list[int]:
        """Идентификаторы всех турниров, подходящих под сохранённые фильтры."""
        settings = await cls.get_settings()
        begin, end = cls.get_period(settings.period_months)
        logger.info("Поиск турниров за период %s — %s", begin, end)

        tour_ids: list[int] = []
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            for tour_rank, location_id in cls.get_filter_pairs(settings):
                tour_ids.extend(
                    await cls.search(http, settings, begin, end, tour_rank, location_id)
                )

        # один турнир мог попасть в несколько сочетаний фильтров
        unique_ids = list(dict.fromkeys(tour_ids))
        logger.info("Найдено турниров: %s", len(unique_ids))
        return unique_ids

    @classmethod
    async def get_settings(cls) -> SearchSettings:
        """Строка параметров поиска; если её нет — завести со значениями по умолчанию."""
        async with async_session() as session:
            settings = await session.get(SearchSettings, SearchSettings.ROW_ID)
            if settings is not None:
                return settings

            logger.warning("Параметры поиска не заданы, создаём строку по умолчанию")
            await session.execute(
                insert(SearchSettings).values(id=SearchSettings.ROW_ID).on_conflict_do_nothing()
            )
            await session.commit()
            return await session.get(SearchSettings, SearchSettings.ROW_ID)

    @classmethod
    def get_filter_pairs(cls, settings: SearchSettings) -> list[tuple[int | None, int | None]]:
        """Сочетания «ранг — локация», которые надо перебрать.

        Пустой список в настройках означает, что фильтра по этому полю нет.
        """
        ranks = settings.tour_ranks or [None]
        locations = settings.location_ids or [None]
        return list(itertools.product(ranks, locations))

    @classmethod
    async def search(
        cls,
        http: aiohttp.ClientSession,
        settings: SearchSettings,
        begin: date,
        end: date,
        tour_rank: int | None,
        location_id: int | None,
    ) -> list[int]:
        """Идентификаторы турниров по одному сочетанию «ранг — локация»."""
        tour_ids: list[int] = []
        page_no = 1
        while page_no <= cls.MAX_PAGES:
            data = await cls.fetch_tours(
                http, settings, begin, end, tour_rank, location_id, page_no
            )
            tour_ids.extend(cls.get_page_tour_ids(data))

            if page_no >= cls.get_page_max(data):
                break
            page_no += 1

        logger.info(
            "Ранг %s, локация %s: найдено турниров %s", tour_rank, location_id, len(tour_ids)
        )
        return tour_ids

    @classmethod
    def get_period(cls, period_months: int) -> tuple[date, date]:
        """Период поиска: с сегодняшнего дня на `period_months` месяцев вперёд."""
        begin = date.today()
        month = begin.month - 1 + period_months
        year = begin.year + month // 12
        month = month % 12 + 1
        # в коротком месяце конца периода может не быть такого числа
        day = min(begin.day, calendar.monthrange(year, month)[1])
        return begin, date(year, month, day)

    @classmethod
    async def fetch_tours(
        cls,
        http: aiohttp.ClientSession,
        settings: SearchSettings,
        begin: date,
        end: date,
        tour_rank: int | None,
        location_id: int | None,
        page_no: int,
    ) -> dict:
        """Запросить страницу списка турниров по одному рангу и одной локации."""
        age_groups = [str(group) for group in settings.age_groups]
        form = [
            # ruid — метка времени в миллисекундах, как её шлёт браузер
            ("ruid", str(int(time.time() * 1000))),
            ("method[0]", "tour.roster"),
            ("page_no", str(page_no)),
            ("per_page", str(settings.per_page)),
            ("sort_field", "begin_date"),
            ("sort_order", "ASC"),
            ("range", "period"),
            ("begin", begin.isoformat()),
            ("end", end.isoformat()),
            ("tour_gender", str(settings.tour_gender)),
            ("player_age", "|".join(age_groups)),
        ]
        form += [(f"age_group[{i}]", group) for i, group in enumerate(age_groups)]
        if tour_rank is not None:
            # `rank` фильтром не является, но фронт шлёт его парой к `tour_rank`
            form += [("tour_rank", str(tour_rank)), ("rank", str(tour_rank))]
        if location_id is not None:
            form.append(("location_id", str(location_id)))

        async with http.post(API_URL, data=form, headers=HEADERS) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    @classmethod
    def get_page_tour_ids(cls, data: dict) -> list[int]:
        """Идентификаторы турниров из ответа `tour.roster`."""
        records = get_node(data, "tour.roster").get("records") or []
        return [record["tour_id"] for record in records if record.get("tour_id")]

    @classmethod
    def get_page_max(cls, data: dict) -> int:
        """Число страниц в выдаче; без навигатора считаем, что страница одна."""
        navigator = get_node(data, "tour.roster").get("navigator") or {}
        return navigator.get("page_max") or 1
