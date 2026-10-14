from fastapi import FastAPI

from src.api.tours import router as tours_router

app = FastAPI(title="RTT monitoring")
app.include_router(tours_router)


@app.get("/health", tags=["service"])
async def health() -> dict[str, str]:
    """Проба для healthcheck контейнера."""
    return {"status": "ok"}
