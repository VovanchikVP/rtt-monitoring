import time
import aiohttp
from src.const import API_URL, HEADERS, RATING_FIELD


def get_player_ids(data: dict, exclude_left: bool = False) -> list[dict]:
    players = data.get("data", {}).get("tour.card.main", {}).get("players", [])
    return [
        {"player_id": p.get("player_id"), "rating_id": RATING_FIELD}
        for p in players
        if not p.get("leave")
    ]

def get_player_data(data: dict, exclude_left: bool = False) -> dict:
    player = data.get("data", {}).get("rating.details", {}).get("player", {})
    rating = data.get("data", {}).get("rating.details", {}).get("rating", {})
    return {
        "name": player.get("name"),
        "birth_date": player.get("birth_date"),
        "city": player.get("city"),
        "points": rating.get("points") if rating else 0,
    }

async def fetch_tour_players(session: aiohttp.ClientSession, tour_id: int) -> dict:
    # ruid — это метка времени в миллисекундах (1791619400024 = 10.10.2026 08:03:20 UTC)
    form = [
        ("ruid", str(int(time.time() * 1000))),
        ("method[0]", "tour.card.main"),
        ("tour_id", str(tour_id)),
        ("part[0]", "players"),
    ]
    async with session.post(API_URL, data=form, headers=HEADERS) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)