import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api.middleware import log_requests
from src.api.routers import players_router, tours_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# uvicorn пишет свою строку на каждый запрос, но без длительности:
# access-лог ведёт middleware, чтобы на запрос приходилась одна строка
logging.getLogger("uvicorn.access").disabled = True

app = FastAPI(title="RTT monitoring")
app.middleware("http")(log_requests)
app.include_router(tours_router)
app.include_router(players_router)


@app.get("/health", tags=["service"])
async def health() -> dict[str, str]:
    """Проба для healthcheck контейнера."""
    return {"status": "ok"}


# монтируется последним: маршруты API уже зарегистрированы и имеют приоритет
app.mount("/", StaticFiles(directory="static", html=True), name="static")
