import asyncio

import aiohttp

from src.const import TOUR_ID
from src.plyer import fetch_rating_details
from src.service import fetch_tour_players, get_player_data, get_player_ids


async def main():
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        result = []
        data = await fetch_tour_players(session, TOUR_ID)
        for i in get_player_ids(data):
            result.append(get_player_data(await fetch_rating_details(session, **i)))
        result.sort(key=lambda r: r["points"], reverse=True)
        for num, r in enumerate(result, start=1):
            print(num, *r.values())


if __name__ == "__main__":
    asyncio.run(main())
