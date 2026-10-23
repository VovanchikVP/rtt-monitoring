import logging
import threading

from src.celery.app import celery_app
from src.const import THROTTLE_DELAY, THROTTLE_MAX_DELAY

logger = logging.getLogger(__name__)

# таймер возобновления один на процесс: повторная блокировка его продлевает
_timer: threading.Timer | None = None
_lock = threading.Lock()
# сколько раз подряд упёрлись в проверку, не пройдя между этим ни одного запроса
_failures = 0


def next_delay(retry_after: int) -> int:
    """Сколько ждать до следующей попытки.

    Пауза от самого API главнее, но у проверки она нулевая — тогда ждём сами
    и с каждой неудачей вдвое дольше. Фиксированная пауза тут не работает:
    проверка держится дольше любого числа, которое можно угадать заранее,
    и возвращаться к ней раз в десять минут — значит продлевать её же.
    """
    global _failures

    _failures += 1
    if retry_after > 0:
        return retry_after
    return min(THROTTLE_DELAY * 2 ** (_failures - 1), THROTTLE_MAX_DELAY)


def clear() -> None:
    """Запрос прошёл — счёт блокировок подряд начинается заново."""
    global _failures

    _failures = 0


def queue_name() -> str:
    """Очередь, из которой воркер разбирает задачи."""
    return celery_app.conf.task_default_queue


def pause_consuming(worker: str | None, seconds: int) -> None:
    """Перестать разбирать очередь на `seconds` секунд.

    Отложить одну задачу мало: следующая возьмётся из очереди сразу и упрётся
    в ту же проверку, продлевая блокировку. Поэтому воркер отписывается от
    очереди целиком и подписывается обратно по таймеру.

    Отписка не трогает служебную очередь команд, так что `add_consumer`
    до воркера дойдёт. Таймер живёт в процессе воркера: если воркер
    перезапустят, подписка восстановится сама из конфигурации.
    """
    global _timer

    queue = queue_name()
    with _lock:
        if _timer is not None:
            # блокировку подтвердили заново — отсчёт начинается сначала
            _timer.cancel()
        celery_app.control.cancel_consumer(queue, destination=destination(worker))
        _timer = threading.Timer(seconds, resume_consuming, args=(worker,))
        _timer.daemon = True
        _timer.start()

    logger.warning("Разбор очереди %s остановлен на %s с", queue, seconds)


def resume_consuming(worker: str | None) -> None:
    """Вернуться к разбору очереди."""
    global _timer

    queue = queue_name()
    with _lock:
        _timer = None
        celery_app.control.add_consumer(queue, destination=destination(worker))

    logger.info("Разбор очереди %s возобновлён", queue)


def destination(worker: str | None) -> list[str] | None:
    """Кому адресовать команду: своему воркеру, а без имени — всем."""
    return [worker] if worker else None


def is_paused() -> bool:
    """Ждёт ли воркер возобновления разбора очереди."""
    return _timer is not None
