import asyncio
import logging
import time
from datetime import date

import aiohttp
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from src.celery.app import celery_app
from src.celery.service.dates import parse_date
from src.celery.service.fill_rating_history import FillRatingHistoryService
from src.const import API_URL, HEADERS, HTTP_TIMEOUT, REQUEST_DELAY
from src.models import Matches, Players, Tours
from src.models.base import async_session

logger = logging.getLogger(__name__)


class FillMatchesService:
    """Матчи турнира из внешнего API.

    Источников два. Часть `matches` карточки `tour.card.main` — это
    расписание: его заполняют не все организаторы, и у большинства турниров
    она приходит пустой. Сыгранные матчи при этом лежат в сетках этапов,
    которые отдаёт `tour.card.grid`: ячейка сетки несёт обоих игроков,
    победителя, счёт по сетам и геймам и дату. Поэтому расписание берём,
    когда оно есть, иначе обходим сетки всех этапов турнира.

    Раз в сутки планировщик ставит отдельную задачу на каждый турнир, который
    уже начался, но ещё не помечен завершённым. Задачи разводятся по времени
    на `REQUEST_DELAY` секунд — внешнее API не любит частых обращений.

    Матчи турнира переписываются целиком: по ходу турнира у матча меняются
    счёт и статус, а своего ключа для сопоставления в таблице нет.
    """

    # не чаще одного запуска в REQUEST_DELAY секунд на воркера
    RATE_LIMIT = f"{60 // REQUEST_DELAY}/m"

    @classmethod
    async def schedule_all(cls) -> int:
        """Поставить задачу разбора матчей на каждый подходящий турнир."""
        tour_ids = await cls.get_tour_ids()
        if not tour_ids:
            logger.info("Турниров для разбора матчей нет")
            return 0

        for number, tour_id in enumerate(tour_ids):
            celery_app.send_task("matches.fill", args=[tour_id], countdown=number * REQUEST_DELAY)
        logger.info("Поставлено задач на разбор матчей: %s", len(tour_ids))
        return len(tour_ids)

    @classmethod
    async def get_tour_ids(cls) -> list[int]:
        """Турниры, которые уже начались и ещё не помечены завершёнными."""
        async with async_session() as session:
            return list(
                await session.scalars(
                    select(Tours.id).where(
                        Tours.is_finished.is_(False),
                        Tours.begin_date.is_not(None),
                        Tours.begin_date < date.today(),
                    )
                )
            )

    @classmethod
    async def run(cls, tour_id: int) -> int:
        """Разобрать матчи одного турнира. Возвращает число записанных матчей."""
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        new_players: list[int] = []
        async with aiohttp.ClientSession(timeout=timeout) as http:
            data = await cls.fetch_tour_matches(http, tour_id)
            matches = cls.get_matches(data, tour_id)
            if not matches:
                # расписания у турнира нет — идём за сетками его этапов
                matches = await cls.collect_grids(http, tour_id, cls.get_stage_ids(data))
            if matches:
                # внешний ключ не даст записать матч игрока, которого нет в базе
                known = await cls.get_known_players(cls.get_player_ids(matches))
                new_players = await cls.add_players(http, cls.get_player_ids(matches) - known)
                known |= set(new_players)

        saved = 0
        if matches:
            playable = [m for m in matches if cls.is_playable(m, known)]
            skipped = len(matches) - len(playable)
            if skipped:
                logger.warning("Турнир %s: пропущено матчей без игрока в базе %s", tour_id, skipped)

            saved = await cls.save_matches(tour_id, playable)
            logger.info("Турнир %s: записано матчей %s", tour_id, saved)
        else:
            logger.info("Турнир %s: матчей в ответе нет", tour_id)

        # карточка приходит тем же ответом; обновляем её после матчей, чтобы
        # сбой на записи матчей не успел пометить турнир завершённым
        await cls.update_tour(tour_id, cls.get_tour_card(data))

        # по новым игрокам сразу добираем очки, не дожидаясь суточного запуска
        FillRatingHistoryService.schedule(new_players)
        return saved

    @classmethod
    async def fetch_tour_matches(cls, http: aiohttp.ClientSession, tour_id: int) -> dict:
        """Запросить карточку турнира вместе с его матчами."""
        form = [
            # ruid — метка времени в миллисекундах, как её шлёт браузер
            ("ruid", str(int(time.time() * 1000))),
            ("method[0]", "tour.card.main"),
            ("tour_id", str(tour_id)),
            ("part[0]", "matches"),
            # этапы нужны, чтобы знать, какие сетки запрашивать
            ("part[1]", "stages"),
        ]
        async with http.post(API_URL, data=form, headers=HEADERS) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    @classmethod
    def get_matches(cls, data: dict, tour_id: int) -> list[dict]:
        """Матчи из ответа `tour.card.main` в виде полей таблицы `matches`."""
        matches = data.get("data", {}).get("tour.card.main", {}).get("matches") or []
        parsed = []
        for match in matches:
            # в сетке есть пары, куда соперник ещё не вышел: там стоит 0
            first = match.get("m1p1") or None
            second = match.get("m2p1") or None
            if first is None or second is None:
                continue

            parsed.append(
                {
                    "tour_id": tour_id,
                    "first_player_id": first,
                    "second_player_id": second,
                    # winner: 1 — победила первая сторона, 2 — вторая, 0 — ещё никто
                    "winner_player_id": {1: first, 2: second}.get(match.get("winner")),
                    "first_score": match.get("score1"),
                    "second_score": match.get("score2"),
                    "score": match.get("score") or None,
                    "status": match.get("status_n") or None,
                    "date": parse_date(match.get("match_date")),
                }
            )
        return parsed

    @classmethod
    def get_stage_ids(cls, data: dict) -> list[int]:
        """Идентификаторы этапов турнира из ответа `tour.card.main`."""
        stages = data.get("data", {}).get("tour.card.main", {}).get("stages") or []
        return [stage["stage_id"] for stage in stages if stage.get("stage_id")]

    @classmethod
    async def collect_grids(
        cls, http: aiohttp.ClientSession, tour_id: int, stage_ids: list[int]
    ) -> list[dict]:
        """Матчи из сеток всех этапов турнира, с паузой между запросами."""
        matches: list[dict] = []
        for number, stage_id in enumerate(stage_ids):
            if number:
                await cls.pause()
            try:
                data = await cls.fetch_stage_grid(http, tour_id, stage_id)
            except Exception:
                # один сбойный этап не должен ронять остальные
                logger.exception("Турнир %s: не удалось получить сетку этапа %s", tour_id, stage_id)
                continue
            matches.extend(cls.get_grid_matches(data, tour_id))
        return matches

    @classmethod
    async def fetch_stage_grid(
        cls, http: aiohttp.ClientSession, tour_id: int, stage_id: int
    ) -> dict:
        """Запросить сетку одного этапа турнира."""
        form = [
            # ruid — метка времени в миллисекундах, как её шлёт браузер
            ("ruid", str(int(time.time() * 1000))),
            ("method[0]", "tour.card.grid"),
            ("tour_id", str(tour_id)),
            ("stage_id", str(stage_id)),
        ]
        async with http.post(API_URL, data=form, headers=HEADERS) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    @classmethod
    def get_grid_matches(cls, data: dict, tour_id: int) -> list[dict]:
        """Матчи из ответа `tour.card.grid` в виде полей таблицы `matches`."""
        grids = data.get("data", {}).get("tour.card.grid", {}).get("grids") or []
        parsed = []
        for grid in grids:
            for cell in grid.get("cells") or []:
                match = cls.get_grid_match(cell, tour_id)
                if match is not None:
                    parsed.append(match)
        return parsed

    @classmethod
    def get_grid_match(cls, cell: dict, tour_id: int) -> dict | None:
        """Ячейка сетки в поля таблицы `matches`; None, если матча в ней нет."""
        # в сетке есть ячейки, куда игрок ещё не вышел: там стоит 0
        first = cell.get("m1p1") or None
        second = cell.get("m2p1") or None
        if first is None or second is None:
            return None
        # парный матч в таблицу не положить: под матч заведены два игрока
        if cell.get("m1p2") or cell.get("m2p2"):
            return None

        # winner: 1 — победила первая сторона, 2 — вторая, 0 — ещё никто
        winner = {1: first, 2: second}.get(cell.get("winner"))
        score = cls.clean_score(cell.get("score"))
        # у несыгранной ячейки счёт по сетам приходит нулями — это не 0:0
        played = winner is not None or score is not None
        return {
            "tour_id": tour_id,
            "first_player_id": first,
            "second_player_id": second,
            "winner_player_id": winner,
            "first_score": cell.get("score1") if played else None,
            "second_score": cell.get("score2") if played else None,
            "score": score,
            "status": cell.get("match_status_v") or None,
            # sdate — дата, на которую матч поставлен; «0», пока её нет
            "date": parse_date(cell.get("sdate")),
        }

    @classmethod
    def clean_score(cls, score: str | None) -> str | None:
        """Счёт по геймам; «0» и пустая строка значат «счёта ещё нет»."""
        value = str(score or "").strip()
        return value if value not in ("", "0") else None

    @classmethod
    def get_tour_card(cls, data: dict) -> dict:
        """Поля турнира из ответа `tour.card.main`, которые стоит освежить."""
        card = data.get("data", {}).get("tour.card.main") or {}
        return {
            "begin_date": parse_date(card.get("begin_date")),
            "end_date": parse_date(card.get("end_date")),
            "location": card.get("location") or None,
            "location_full": card.get("location_full") or None,
            # в ответе это 0 или 1
            "is_finished": bool(card.get("is_finished")),
        }

    @classmethod
    async def update_tour(cls, tour_id: int, fields: dict) -> None:
        """Обновить карточку турнира по данным того же ответа."""
        async with async_session() as session:
            await session.execute(update(Tours).where(Tours.id == tour_id).values(**fields))
            await session.commit()
        if fields["is_finished"]:
            logger.info("Турнир %s помечен завершённым", tour_id)

    @classmethod
    def get_player_ids(cls, matches: list[dict]) -> set[int]:
        """Идентификаторы всех игроков, встречающихся в матчах."""
        ids = set()
        for match in matches:
            ids.add(match["first_player_id"])
            ids.add(match["second_player_id"])
        return ids

    @classmethod
    def is_playable(cls, match: dict, known: set[int]) -> bool:
        """Можно ли записать матч: оба игрока есть в базе."""
        return match["first_player_id"] in known and match["second_player_id"] in known

    @classmethod
    async def get_known_players(cls, player_ids: set[int]) -> set[int]:
        """Те из переданных игроков, что уже есть в базе."""
        if not player_ids:
            return set()
        async with async_session() as session:
            return set(await session.scalars(select(Players.id).where(Players.id.in_(player_ids))))

    @classmethod
    async def add_players(cls, http: aiohttp.ClientSession, player_ids: set[int]) -> list[int]:
        """Дозавести игроков отдельными запросами. Возвращает добавленных."""
        added = []
        for number, player_id in enumerate(sorted(player_ids)):
            if number:
                await cls.pause()
            try:
                data = await cls.fetch_player(http, player_id)
            except Exception:
                # один сбойный игрок не должен ронять остальных
                logger.exception("Не удалось получить карточку игрока %s", player_id)
                continue

            player = cls.get_player(data, player_id)
            if player is None:
                logger.warning("Игрок %s: в карточке нет имени или даты рождения", player_id)
                continue

            async with async_session() as session:
                await session.execute(
                    insert(Players).values(player).on_conflict_do_nothing(index_elements=["id"])
                )
                await session.commit()
            added.append(player_id)

        if added:
            logger.info("Добавлено новых игроков: %s", len(added))
        return added

    @classmethod
    async def fetch_player(cls, http: aiohttp.ClientSession, player_id: int) -> dict:
        """Запросить карточку игрока."""
        form = [
            ("ruid", str(int(time.time() * 1000))),
            ("method[0]", "player.card.main"),
            ("player_id", str(player_id)),
        ]
        async with http.post(API_URL, data=form, headers=HEADERS) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    @classmethod
    def get_player(cls, data: dict, player_id: int) -> dict | None:
        """Поля таблицы `players` из ответа `player.card.main`.

        None, если не хватает обязательных полей: имени или даты рождения.
        """
        card = data.get("data", {}).get("player.card.main") or {}
        name = " ".join(
            part for part in (card.get(key) for key in ("name_f", "name_i", "name_o")) if part
        )
        birth_date = parse_date(card.get("birth_date"))
        if not name or birth_date is None:
            return None

        # в карточке город записан путём «Рязань, Рязанская область, …»,
        # а в составах турниров — одним городом; приводим к короткому виду
        city = (card.get("doc_city") or "").split(",")[0].strip() or None
        return {"id": player_id, "name": name, "birth_date": birth_date, "city": city}

    @classmethod
    async def save_matches(cls, tour_id: int, matches: list[dict]) -> int:
        """Переписать матчи турнира. Возвращает число записанных."""
        if not matches:
            return 0

        async with async_session() as session:
            # счёт и статус матча меняются по ходу турнира, а своего ключа
            # у матча в таблице нет — проще переписать турнир целиком
            await session.execute(delete(Matches).where(Matches.tour_id == tour_id))
            result = await session.execute(insert(Matches).values(matches))
            await session.commit()

        return result.rowcount

    @classmethod
    async def pause(cls) -> None:
        """Пауза между запросами: частых обращений внешнее API не прощает."""
        await asyncio.sleep(REQUEST_DELAY)
