import time
import aiohttp
from src.const import API_URL, HEADERS


def _ruid() -> str:
    # метка времени в миллисекундах, как в браузере
    return str(int(time.time() * 1000))


async def _call(session: aiohttp.ClientSession, form: list[tuple[str, str]]) -> dict:
    async with session.post(API_URL, data=form, headers=HEADERS) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)


async def fetch_rating_details(
    session: aiohttp.ClientSession, rating_id: int, player_id: int
) -> dict:
    form = [
        ("ruid", _ruid()),
        ("method[0]", "rating.details"),
        ("rating_id", str(rating_id)),
        ("player_id", str(player_id)),
    ]
    return await _call(session, form)


async def fetch_tour_players(session: aiohttp.ClientSession, tour_id: int) -> dict:
    form = [
        ("ruid", _ruid()),
        ("method[0]", "tour.card.main"),
        ("tour_id", str(tour_id)),
        ("part[0]", "players"),
    ]
    return await _call(session, form)


async def main():
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        details = await fetch_rating_details(session, 202610011, 101177)
        print(details)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())