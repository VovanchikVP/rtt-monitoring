# RTT monitoring

Сервис следит за турнирами Российского теннисного тура: по id турнира сам
подтягивает карточку и состав участников с внешнего API, хранит историю
рейтинговых очков игроков и показывает актуальный список участников,
отсортированный по очкам.

## Как это работает

```
            ┌──────────┐   POST /tours    ┌───────────┐
  браузер ──┤ FastAPI  ├─────задача──────▶│ RabbitMQ  │
            │ + статика│                  └─────┬─────┘
            └────┬─────┘                        │
                 │                        ┌─────▼─────┐   HTTP   ┌──────────────┐
                 │                        │  celery   ├─────────▶│ API rtt      │
                 │                        │ worker    │          │ mytennis.online
                 │                        └─────┬─────┘          └──────────────┘
                 │                              │
              ┌──▼──────────────────────────────▼──┐      ┌──────────────┐
              │            PostgreSQL              │◀─────┤ celery beat  │
              └────────────────────────────────────┘      └──────────────┘
```

Эндпоинт только заводит запись турнира с одним полем `id` и ставит задачу в
очередь. Всё остальное — запрос к внешнему API, заполнение карточки, добор
игроков, связей и очков — делают фоновые задачи. Поэтому создание турнира
отвечает мгновенно и не зависит от доступности источника данных.

## Запуск локально

```bash
docker compose up -d --build
```

Поднимается всё сразу: PostgreSQL, RabbitMQ, API, worker и beat. Миграции
накатываются автоматически перед стартом API.

- интерфейс — http://localhost:8000
- документация API — http://localhost:8000/docs
- панель RabbitMQ — http://localhost:15672

Полезные переменные при запуске: `APP_PORT`, `APP_RABBITMQ_UI_PORT`,
`APP_FILL_TOURS_INTERVAL`.

### Без докера

Нужны запущенные PostgreSQL и RabbitMQ, параметры подключения — в `.env`
(за образец можно взять `.env.example`).

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app:app --reload
uv run celery -A src.celery.app:celery_app worker --loglevel=info
uv run celery -A src.celery.app:celery_app beat --loglevel=info
```

## API

| Метод | Путь | Что делает |
|---|---|---|
| `GET` | `/tours` | список отслеживаемых турниров с числом участников |
| `POST` | `/tours` | добавить турнир по `id`, остальное заполнится само |
| `DELETE` | `/tours/{id}` | удалить турнир и его связи с игроками |
| `GET` | `/tours/{id}/players` | состав турнира, по убыванию очков |
| `GET` | `/health` | проба для healthcheck |

`POST /tours` принимает единственное поле и отвергает лишние:

```bash
curl -X POST localhost:8000/tours -H 'Content-Type: application/json' -d '{"id": 307095}'
```

Ответ `GET /tours/{id}/players`:

```json
[{"number": 1, "id": 100505, "name": "Иванова Анна Сергеевна",
  "age": 11, "city": "Хабаровск", "points": 510}]
```

## Фоновые задачи

| Задача | Когда запускается | Что делает |
|---|---|---|
| `tours.fill_empty` | после `POST /tours` и каждые `FILL_TOURS_INTERVAL` секунд | находит турниры без данных, тянет карточку, добавляет игроков и связи |
| `points.fill` | следом за `tours.fill_empty` и раз в сутки в `FILL_POINTS_HOUR` | добирает очки игрокам, у которых нет записи за текущий месяц |
| `tours.sync_players` | раз в сутки в `SYNC_TOURS_HOUR` | сверяет составы ещё не начавшихся турниров: добавляет недостающих, убирает лишние связи |
| `tours.search` | раз в сутки в `SEARCH_TOURS_HOUR` | ищет турниры по фильтрам из `search_settings` и ставит на отслеживание новые |

Задачи идемпотентны: повторный запуск не создаёт дублей. Старые записи об
очках не удаляются — копится история, по одной записи на игрока в месяц.

## Интерфейс

`static/index.html` — одна страница без сборки, отдаётся самим FastAPI.
Список турниров опрашивается каждые 3 секунды, **пока есть незаполненные
турниры**; как только все данные подтянуты, опрос прекращается. Состав
участников открывается по прямой ссылке вида `/#tour=307095`.

## Конфигурация

Все переменные читаются из окружения, локально — из `.env`;
полный список с примерами значений — в `.env.example`.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `APP_DB_HOST` / `APP_DB_NAME` / `APP_DB_USER` / `APP_DB_PASSWORD` | — | подключение к PostgreSQL |
| `APP_RABBITMQ_HOST` | `localhost` | адрес брокера |
| `APP_RABBITMQ_PORT` | `5672` | порт брокера |
| `APP_RABBITMQ_USER` / `APP_RABBITMQ_PASSWORD` | `guest` | учётные данные брокера |
| `APP_RABBITMQ_VHOST` | `/` | виртуальный хост |
| `APP_FILL_TOURS_INTERVAL` | `300` | период поиска незаполненных турниров, секунды |
| `APP_FILL_POINTS_HOUR` | `3` | час UTC для обновления очков |
| `APP_SYNC_TOURS_HOUR` | `4` | час UTC для сверки составов |
| `APP_SEARCH_TOURS_HOUR` | `5` | час UTC для автоматического поиска турниров |

## Структура

```
app.py                      точка входа FastAPI, монтирование статики
src/api/routers/            эндпоинты: только сигнатуры и вызов сервиса
src/api/schemas/            схемы запросов и ответов
src/service/                бизнес-логика эндпоинтов
src/celery/app.py           инстанс celery, расписание beat
src/celery/tasks.py         определения задач
src/celery/service/         бизнес-логика задач, по файлу на задачу
src/models/                 модели SQLAlchemy
migration/                  миграции alembic
static/index.html           интерфейс
ci/                         манифесты k3s, см. ci/README.md
```

Схема данных: `tours` — турниры, `players` — игроки, `tours_players` —
связь многие-ко-многим, `points` — история очков с уникальным ключом
`(players_id, date)`.

## Разработка

```bash
uv sync                      # зависимости
uv run pre-commit install    # хуки на коммит
uv run ruff check . && uv run ruff format .
uv run pre-commit run --all-files
```

Новая миграция после правки моделей:

```bash
uv run alembic revision --autogenerate -m "описание"
uv run alembic upgrade head
```

## Выкатка

Сборка образа и деплой в k3s настроены в GitHub Actions: `.github/workflows/ci.yml`
прогоняет линтеры и проверяет манифесты, `cd.yml` собирает образ в GHCR и
раскатывает его в кластер. Манифесты и порядок первой установки —
в [ci/README.md](ci/README.md).
