import logging

import aiohttp

from src.celery.app import celery_app
from src.celery.service.fill_points import FillPointsService
from src.const import HTTP_TIMEOUT, REQUEST_DELAY

logger = logging.getLogger(__name__)


class FillPlayerToursService:
    """Обновление результатов игрока по сыгранным турнирам.

    Ответ `rating.details` текущего рейтинг-листа несёт турниры, которые идут
    игроку в зачёт, — это последний год. Место и очки за турнир со временем
    пересчитываются, поэтому записи в `rating_details` переписываются
    свежими значениями, а незнакомые турниры заодно заводятся в `tours`.

    Задача ставится по одной на игрока: ежедневная `points.fill` трогает
    только тех, у кого нет очков за текущий месяц, а `points.fill_history` —
    только месяцы без записей, так что у остальных игроков результаты
    турниров остаются такими, какими их увидели в первый раз.
    """

    # не чаще одного запуска в REQUEST_DELAY секунд на воркера
    RATE_LIMIT = f"{60 // REQUEST_DELAY}/m"

    @classmethod
    def schedule(cls, player_ids: list[int]) -> None:
        """Поставить задачу обновления турниров на каждого игрока из списка.

        Задачи расходятся по времени ещё на входе в очередь, `rate_limit`
        самой задачи страхует от наплыва.
        """
        if not player_ids:
            return

        for number, player_id in enumerate(player_ids):
            celery_app.send_task(
                "tours.fill_player", args=[player_id], countdown=number * REQUEST_DELAY
            )
        logger.info("Поставлено задач на обновление турниров: %s", len(player_ids))

    @classmethod
    async def run(cls, player_id: int) -> int:
        """Обновить турниры игрока. Возвращает число затронутых записей."""
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            data = await FillPointsService.fetch_rating_details(http, player_id)

        tours = FillPointsService.get_tours(data)
        if not tours:
            logger.info("Игрок %s: сыгранных турниров в ответе нет", player_id)
            return 0

        saved = await FillPointsService.save_rating_details(player_id, tours)
        logger.info("Игрок %s: обновлено результатов турниров %s", player_id, saved)
        return saved
