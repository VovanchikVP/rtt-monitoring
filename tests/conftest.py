"""Общие фикстуры для тестов запросов к внешнему API.

Внешний API подменяется локальным сервером на aiohttp, а не моком клиента:
запрос уходит по-настоящему, и проверить можно то, что реально ушло в сеть —
метод, поля формы и заголовки. Заодно это ловит ошибки кодирования формы,
которые мок не заметит.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import date

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer

from src.celery.service import fill_matches, fill_points, fill_tours, search_tours
from src.const import HTTP_TIMEOUT

# модули, в которых адрес API надо подменить на локальный сервер
API_MODULES = (fill_matches, fill_points, fill_tours, search_tours)


@dataclass
class Recorded:
    """Запрос, пойманный поддельным API."""

    method: str
    path: str
    headers: dict[str, str]
    # значения полей формы; при повторе ключа остаётся последнее
    form: dict[str, str]
    # все пары формы по порядку — нужны там, где важны повторяющиеся ключи
    form_pairs: list[tuple[str, str]] = field(default_factory=list)


class FakeApi:
    """Локальная замена apirtt.mytennis.online.

    Пишет все пришедшие запросы и отдаёт заготовленные ответы: сначала
    очередь из `reply()`, когда она пуста — ответ из `always()`.
    """

    def __init__(self) -> None:
        self.url = ""
        self.requests: list[Recorded] = []
        self._queue: deque[tuple[int, bytes, str]] = deque()
        # настоящий API отвечает JSON'ом с типом text/html, поэтому в коде
        # стоит json(content_type=None) — заглушка ведёт себя так же
        self._default: tuple[int, bytes, str] = (200, b'{"data": {}}', "text/html")

    def reply(
        self,
        payload: str | bytes = b'{"data": {}}',
        *,
        status: int = 200,
        content_type: str = "text/html",
    ) -> None:
        """Поставить в очередь один ответ."""
        self._queue.append((status, _as_bytes(payload), content_type))

    def always(
        self,
        payload: str | bytes = b'{"data": {}}',
        *,
        status: int = 200,
        content_type: str = "text/html",
    ) -> None:
        """Отвечать так на все запросы, для которых не поставлен ответ в очередь."""
        self._default = (status, _as_bytes(payload), content_type)

    @property
    def request(self) -> Recorded:
        """Единственный пойманный запрос; если их не один — тест упадёт здесь."""
        assert len(self.requests) == 1, f"запросов к API: {len(self.requests)}"
        return self.requests[0]

    async def handle(self, request: web.Request) -> web.Response:
        post = await request.post()
        self.requests.append(
            Recorded(
                method=request.method,
                path=request.path,
                headers=dict(request.headers),
                form={key: str(value) for key, value in post.items()},
                form_pairs=[(key, str(value)) for key, value in post.items()],
            )
        )
        status, body, content_type = self._queue.popleft() if self._queue else self._default
        return web.Response(status=status, body=body, content_type=content_type)


def _as_bytes(payload: str | bytes) -> bytes:
    return payload if isinstance(payload, bytes) else payload.encode()


@pytest_asyncio.fixture
async def api(monkeypatch):
    """Поднять поддельный API и направить на него все запросы приложения."""
    fake = FakeApi()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", fake.handle)

    server = TestServer(app)
    await server.start_server()
    fake.url = str(server.make_url("/api/v1/public"))
    for module in API_MODULES:
        monkeypatch.setattr(module, "API_URL", fake.url)

    yield fake

    await server.close()


@pytest_asyncio.fixture
async def http():
    """Сессия с тем же таймаутом, с каким её создаёт приложение."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)) as session:
        yield session


@pytest.fixture
def freeze_date(monkeypatch):
    """Зафиксировать `date.today()` внутри модуля сервиса."""

    def freeze(module, value: date) -> None:
        class Frozen(date):
            @classmethod
            def today(cls) -> date:
                return value

        monkeypatch.setattr(module, "date", Frozen)

    return freeze
