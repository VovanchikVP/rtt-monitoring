import logging
import os
from collections.abc import Mapping

import aiohttp

from src.celery.service.proxy import proxy_service
from src.const import API_URL, HEADERS, THROTTLE_DELAY

logger = logging.getLogger(__name__)

# этим кодом внешнее API отвечает, когда требует пройти проверку
THROTTLED_STATUS = 428


class ThrottledError(Exception):
    """Внешнее API просит подождать: 428 с требованием пройти проверку.

    Капчу фоновой задаче не пройти, поэтому остаётся отложить работу и
    вернуться позже — блокировка снимается сама. Отдельное исключение нужно,
    чтобы отличить эту просьбу от настоящей ошибки: сыпать на неё трассировкой
    и идти дальше по списку бессмысленно, следующий запрос упрётся в то же.
    """

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"внешнее API требует проверку, повтор через {retry_after} с")
        self.retry_after = retry_after


async def post(http: aiohttp.ClientSession, form: list[tuple[str, str]]) -> dict:
    """Запрос к внешнему API. Просьбу подождать отдаёт как `ThrottledError`."""
    params = {"data": form, "headers": HEADERS}
    if "PYTEST_CURRENT_TEST" not in os.environ:
        params["proxy"] = await proxy_service.get()
    try:
        async with http.post(API_URL, **params) as resp:
            if resp.status == THROTTLED_STATUS:
                data = await resp.json(content_type=None)
                raise ThrottledError(get_retry_after(data, resp.headers))
            resp.raise_for_status()
            return await resp.json(content_type=None)
    except aiohttp.ClientHttpProxyError as err:
        logger.error(f"Прокси: {params.get('proxy')} отказал в соединении!")
        await proxy_service.remove(params.get("proxy"))
        raise ThrottledError(THROTTLE_DELAY) from err


def get_retry_after(data: object, headers: Mapping[str, str]) -> int:
    """Сколько секунд ждать до повтора.

    API кладёт `retry_after` в тело ответа, но у проверки он нулевой —
    тогда берём свою паузу: вернувшись сразу, задача упрётся в ту же стену.
    """
    node = data.get("data") if isinstance(data, dict) else None
    from_body = node.get("retry_after") if isinstance(node, dict) else None

    for value in (from_body, headers.get("Retry-After")):
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return seconds
    return THROTTLE_DELAY
