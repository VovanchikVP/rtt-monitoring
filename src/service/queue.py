import logging

from fastapi import HTTPException, status

from src.const import REQUEST_DELAY

logger = logging.getLogger(__name__)


def schedule_each(task: object, ids: list[int]) -> None:
    """Поставить задачу на каждый идентификатор с шагом `REQUEST_DELAY`.

    Задачи расходятся по времени ещё на входе в очередь, `rate_limit` самой
    задачи страхует от наплыва.

    Этим пользуются ручки, запускающие работу по запросу человека:
    периодической задачи на подхват у них нет, поэтому недоступный брокер —
    это 503, а не молча потерянный запрос.
    """
    try:
        for number, value in enumerate(ids):
            task.apply_async(args=[value], countdown=number * REQUEST_DELAY)
    except Exception as error:
        logger.exception("Не удалось поставить задачи в очередь")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Очередь задач недоступна, попробуйте позже",
        ) from error
