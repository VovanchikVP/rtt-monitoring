def get_node(data: dict, method: str) -> dict:
    """Узел ответа внешнего API по имени метода.

    Там, где данных нет, API отдаёт на месте объекта пустой список или null:
    `tour.card.grid` у этапа без сетки — `[]`, `rating.details` по
    неизвестному игроку — `null`. Обращаться к такому ответу как к словарю
    нельзя, поэтому всё, что не объект, превращается в пустой словарь.
    """
    root = data.get("data") if isinstance(data, dict) else None
    node = root.get(method) if isinstance(root, dict) else None
    return node if isinstance(node, dict) else {}
