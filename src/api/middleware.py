import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

# отдельный логгер: access-лог удобно приглушать, не трогая остальные
logger = logging.getLogger("api.access")

CallNext = Callable[[Request], Awaitable[Response]]


async def log_requests(request: Request, call_next: CallNext) -> Response:
    """Записать в лог запрос вместе со временем его выполнения.

    Заменяет access-лог uvicorn: тот же клиент, метод, путь и код ответа,
    но ещё и длительность. Время берётся монотонными часами — перевод
    системных не должен давать отрицательную длительность.
    """
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # обработчик ошибок отработает выше по стеку, но запрос должен
        # попасть в лог в любом случае — иначе он просто исчезнет
        logger.exception("%s → ошибка за %s", describe(request), elapsed(started))
        raise

    logger.info("%s → %s за %s", describe(request), response.status_code, elapsed(started))
    return response


def describe(request: Request) -> str:
    """Клиент, метод и путь запроса — «127.0.0.1 GET /tours?limit=10»."""
    client = request.client.host if request.client else "-"
    query = request.url.query
    path = f"{request.url.path}?{query}" if query else request.url.path
    return f"{client} {request.method} {path}"


def elapsed(started: float) -> str:
    """Время с начала запроса, миллисекунды."""
    return f"{(time.perf_counter() - started) * 1000:.1f} мс"
