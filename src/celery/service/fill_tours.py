import logging

import aiohttp
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.const import HTTP_TIMEOUT
from src.models import Players, Tours, tours_players
from src.models.base import async_session
from src.service import fetch_tour_players, get_tour_main, get_tour_players

logger = logging.getLogger(__name__)


async def fill_empty_tours() -> None:
    """Найти незаполненные турниры и дотянуть по ним данные из внешнего API."""
    async with async_session() as session:
        tour_ids = list(await session.scalars(select(Tours.id).where(Tours.name.is_(None))))

    if not tour_ids:
        logger.info("Незаполненных турниров нет")
        return

    logger.info("Незаполненных турниров: %s", len(tour_ids))
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        for tour_id in tour_ids:
            try:
                await fill_tour(http, tour_id)
            except Exception:
                # один сбойный турнир не должен ронять остальные
                logger.exception("Не удалось заполнить турнир %s", tour_id)


async def fill_tour(http: aiohttp.ClientSession, tour_id: int) -> None:
    """Заполнить карточку турнира, добавить недостающих игроков и связи с турниром."""
    data = await fetch_tour_players(http, tour_id)

    async with async_session() as session:
        tour = await session.get(Tours, tour_id)
        if tour is None:
            logger.warning("Турнир %s исчез из базы, пропускаем", tour_id)
            return

        for field, value in get_tour_main(data).items():
            setattr(tour, field, value)

        players = get_tour_players(data)
        await add_missing_players(session, players)
        await add_missing_links(session, tour_id, [p["id"] for p in players])

        await session.commit()

    logger.info("Турнир %s заполнен, участников: %s", tour_id, len(players))


async def add_missing_players(session: AsyncSession, players: list[dict]) -> None:
    """Добавить в `players` тех, кого там ещё нет."""
    if not players:
        return

    known = set(
        await session.scalars(select(Players.id).where(Players.id.in_([p["id"] for p in players])))
    )
    new = [p for p in players if p["id"] not in known]
    if not new:
        return

    await session.execute(insert(Players).values(new).on_conflict_do_nothing())
    logger.info("Добавлено новых игроков: %s", len(new))


async def add_missing_links(session: AsyncSession, tour_id: int, player_ids: list[int]) -> None:
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
