from src.const import RATING_FIELD


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
