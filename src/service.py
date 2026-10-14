import time
from datetime import date

import aiohttp

from src.const import API_URL, HEADERS, RATING_FIELD

# API отдаёт эту дату как признак «значение не заполнено»
EMPTY_DATE = "1900-01-01"


def parse_date(value: str | None) -> date | None:
    """Дата из ответа API; пустые значения и заглушки превращаются в None."""
    if not value or value.startswith(EMPTY_DATE):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


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


def get_tour_main(data: dict) -> dict:
    """Основные поля карточки турнира из ответа `tour.card.main`."""
    tour = data.get("data", {}).get("tour.card.main", {})
    return {
        "name": tour.get("name"),
        "location": tour.get("location"),
        "location_full": tour.get("location_full"),
        "begin_date": parse_date(tour.get("begin_date")),
        "end_date": parse_date(tour.get("end_date")),
        "tour_members": tour.get("tour_members"),
    }


def get_tour_players(data: dict, exclude_left: bool = True) -> list[dict]:
    """Участники турнира в виде полей таблицы `players`."""
    players = data.get("data", {}).get("tour.card.main", {}).get("players", [])
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
